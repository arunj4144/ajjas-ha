/**
 * KTM Route Card – v3
 * Fixes: Leaflet CSS in shadow DOM (critical for tile/marker positioning),
 *        bike marker always visible, previous ride path, 1:1 ratio.
 */
(function () {
  "use strict";

  const SPEED_COLORS = [
    { max: 20,       color: "#4CAF50" },
    { max: 40,       color: "#8BC34A" },
    { max: 60,       color: "#CDDC39" },
    { max: 80,       color: "#FFC107" },
    { max: 100,      color: "#FF9800" },
    { max: 120,      color: "#FF5722" },
    { max: Infinity, color: "#F44336" },
  ];

  function speedColor(spd) {
    const s = parseFloat(spd) || 0;
    for (const b of SPEED_COLORS) if (s <= b.max) return b.color;
    return "#F44336";
  }

  const LEAFLET_CSS = "/local/leaflet/leaflet.min.css";
  const LEAFLET_JS  = "/local/leaflet/leaflet.min.js";
  let _leafletReady = null;

  function loadLeaflet() {
    if (_leafletReady) return _leafletReady;
    _leafletReady = new Promise((resolve, reject) => {
      if (window.L) { resolve(window.L); return; }
      const s = document.createElement("script");
      s.src = LEAFLET_JS;
      s.onload  = () => resolve(window.L);
      s.onerror = () => reject(new Error("Cannot load " + LEAFLET_JS));
      document.head.appendChild(s);
    });
    return _leafletReady;
  }

  async function snapToRoads(wps) {
    const out = [];
    for (let i = 0; i < wps.length; i += 95) {
      const batch = wps.slice(i, i + 95);
      const coords = batch.map(w => `${w[1]},${w[0]}`).join(";");
      try {
        const r = await fetch(`https://router.project-osrm.org/match/v1/driving/${coords}?overview=full&geometries=geojson`);
        if (!r.ok) throw 0;
        const d = await r.json();
        if (d.matchings && d.matchings[0]) {
          d.matchings[0].geometry.coordinates.forEach((c, idx) =>
            out.push([c[1], c[0], batch[Math.min(idx, batch.length - 1)][2]]));
        } else batch.forEach(w => out.push(w));
      } catch (_) { batch.forEach(w => out.push(w)); }
    }
    return out;
  }

  class KtmRouteCard extends HTMLElement {
    constructor() {
      super();
      this._hass       = null;
      this._config     = {};
      this._map        = null;
      this._layers     = [];
      this._lastKey    = "";
      this._rendering  = false;
      this._ro         = null;
      this.attachShadow({ mode: "open" });
    }

    setConfig(config) {
      this._config = { title: "KTM 390 ADV Route", snap_to_roads: false, ...config };
      this._build();
    }

    set hass(hass) {
      this._hass = hass;
      this._tryUpdate();
    }

    getCardSize() { return 8; }

    connectedCallback() {
      if (this._map) setTimeout(() => this._map && this._map.invalidateSize(true), 200);
    }

    disconnectedCallback() {
      if (this._ro) { this._ro.disconnect(); this._ro = null; }
    }

    _tryUpdate() {
      if (this._map && this._hass) this._updateCard();
    }

    _build() {
      const title = this._config.title || "KTM 390 ADV Route";

      // ── Leaflet CSS must live inside shadow root for pane/marker positioning ──
      const leafletCss = document.createElement("link");
      leafletCss.rel  = "stylesheet";
      leafletCss.href = LEAFLET_CSS;

      const style = document.createElement("style");
      style.textContent = `
        :host { display: block; }
        ha-card { overflow: hidden; background: var(--ha-card-background, #1c1c1e); }
        .card-header {
          display: flex; align-items: center; justify-content: space-between;
          padding: 12px 16px 8px;
          font-size: 1rem; font-weight: 500;
          color: var(--primary-text-color, #fff);
        }
        .badge { font-size: .72rem; font-weight: 700; padding: 3px 10px;
          border-radius: 12px; text-transform: uppercase; letter-spacing: .05em; }
        .badge-riding { background: #FF6600; color: #fff; }
        .badge-parked { background: #555;    color: #ccc; }

        /* 1:1 square – inner map fills it absolutely */
        #map-wrap { width: 100%; aspect-ratio: 1 / 1; position: relative; background: #1a1a2e; }
        #map      { position: absolute; inset: 0; }

        /* Make Leaflet controls/popups visible over shadow styles */
        .leaflet-container { background: #1a1a2e; }
        .leaflet-control-zoom a { color: #333; }
        .ktm-tooltip {
          background: rgba(0,0,0,.75) !important;
          color: #fff !important; border: none !important;
          font-size: .8rem; padding: 3px 7px; border-radius: 4px;
        }
        .ktm-tooltip::before { display: none !important; }

        .stats-bar { display: flex; border-top: 1px solid var(--divider-color,#333);
          background: var(--ha-card-background,#1c1c1e); }
        .stat { flex: 1; text-align: center; padding: 8px 4px; }
        .stat-label { font-size: .65rem; color: var(--secondary-text-color,#aaa);
          text-transform: uppercase; letter-spacing: .04em; }
        .stat-value { font-size: .95rem; font-weight: 600; color: var(--primary-text-color,#fff); }
        .speed-legend { display: flex; height: 5px; }
        .speed-legend-seg { flex: 1; }
      `;

      const card = document.createElement("ha-card");

      const header = document.createElement("div");
      header.className = "card-header";
      header.innerHTML = `<span>${title}</span>
        <span class="badge badge-parked" id="riding-badge">Parked</span>`;

      const mapWrap = document.createElement("div");
      mapWrap.id = "map-wrap";
      const mapDiv = document.createElement("div");
      mapDiv.id = "map";
      mapWrap.appendChild(mapDiv);

      const statsBar = document.createElement("div");
      statsBar.className = "stats-bar";
      statsBar.innerHTML = `
        <div class="stat"><div class="stat-label">Distance</div>
          <div class="stat-value" id="s-dist">—</div></div>
        <div class="stat"><div class="stat-label">Speed</div>
          <div class="stat-value" id="s-spd">—</div></div>
        <div class="stat"><div class="stat-label">Points</div>
          <div class="stat-value" id="s-pts">—</div></div>`;

      const legend = document.createElement("div");
      legend.className = "speed-legend";
      SPEED_COLORS.forEach(b => {
        const seg = document.createElement("div");
        seg.className = "speed-legend-seg";
        seg.style.background = b.color;
        legend.appendChild(seg);
      });

      card.append(header, mapWrap, statsBar, legend);

      this.shadowRoot.innerHTML = "";
      this.shadowRoot.append(leafletCss, style, card);

      this._mapDiv = mapDiv;
      this._map    = null;
      this._layers = [];

      loadLeaflet()
        .then(() => this._initMap())
        .catch(err => {
          mapDiv.style.cssText = "display:flex;align-items:center;justify-content:center;height:200px;color:#aaa";
          mapDiv.textContent = err.message;
        });
    }

    _initMap() {
      const L = window.L;
      if (!L || !this._mapDiv) return;

      // Suppress missing default marker images
      delete L.Icon.Default.prototype._getIconUrl;
      L.Icon.Default.mergeOptions({ iconUrl: false, iconRetinaUrl: false, shadowUrl: false });

      this._map = L.map(this._mapDiv, {
        zoomControl: true,
        attributionControl: false,
        preferCanvas: true,
      });

      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19, keepBuffer: 4,
        updateWhenIdle: false, updateWhenZooming: true,
      }).addTo(this._map);

      L.control.attribution({ prefix: false, position: "bottomright" })
        .addAttribution("© OpenStreetMap").addTo(this._map);

      this._map.setView([12.94, 77.61], 14);

      // ResizeObserver keeps tiles fresh when the card resizes
      if (window.ResizeObserver) {
        this._ro = new ResizeObserver(() => this._map && this._map.invalidateSize(true));
        this._ro.observe(this._mapDiv);
      }

      // Two rAFs: first waits for layout, second waits for paint
      requestAnimationFrame(() => requestAnimationFrame(() => {
        if (!this._map) return;
        this._map.invalidateSize(true);
        this._tryUpdate();
      }));
    }

    // ── entity helpers ────────────────────────────────────────────────────

    _getEntity() {
      if (!this._hass) return null;
      if (this._config.entity) return this._hass.states[this._config.entity] || null;
      const id = Object.keys(this._hass.states)
        .find(k => k.startsWith("sensor.") && k.includes("ride_track"));
      return id ? this._hass.states[id] : null;
    }

    _getTracker() {
      if (!this._hass) return null;
      const id = Object.keys(this._hass.states)
        .find(k => k.startsWith("device_tracker.") && (k.includes("ktm") || k.includes("ajjas")));
      return id ? this._hass.states[id] : null;
    }

    // ── update ────────────────────────────────────────────────────────────

    _updateCard() {
      if (this._rendering) return;

      const entity  = this._getEntity();
      const tracker = this._getTracker();

      const isRiding  = entity?.state === "riding";
      const attrs     = entity?.attributes || {};
      const wps       = attrs.waypoints           || [];
      const lastWps   = attrs.last_ride_waypoints || [];
      const dist      = attrs.ride_distance_km    || 0;
      const ptCount   = attrs.waypoint_count      || wps.length;

      const ta  = tracker?.attributes || {};
      const lat = ta.latitude  != null ? parseFloat(ta.latitude)  : null;
      const lon = ta.longitude != null ? parseFloat(ta.longitude) : null;
      const spd = parseFloat(ta.speed_kmh || 0);

      const key = `${isRiding}|${ptCount}|${lastWps.length}|${lat}|${lon}|${spd}`;
      if (key === this._lastKey) return;
      this._lastKey = key;

      // Badge
      const badge = this.shadowRoot.getElementById("riding-badge");
      if (badge) {
        badge.textContent = isRiding ? "Riding" : "Parked";
        badge.className   = isRiding ? "badge badge-riding" : "badge badge-parked";
      }

      // Stats
      const el = id => this.shadowRoot.getElementById(id);
      const sd = el("s-dist"), ss = el("s-spd"), sp = el("s-pts");
      if (sd) sd.textContent = dist ? `${dist.toFixed(2)} km`
                             : (lastWps.length ? "prev ride" : "—");
      if (ss) ss.textContent = isRiding ? `${spd.toFixed(0)} km/h` : (spd > 0 ? `${spd.toFixed(0)} km/h` : "—");
      if (sp) sp.textContent = ptCount || (lastWps.length ? `${lastWps.length} prev` : "—");

      const activeWps = isRiding ? wps : [];

      if (this._config.snap_to_roads && activeWps.length >= 2) {
        this._rendering = true;
        snapToRoads(activeWps)
          .then(s  => this._render(s, lastWps, lat, lon, isRiding, spd))
          .catch(() => this._render(activeWps, lastWps, lat, lon, isRiding, spd))
          .finally(() => { this._rendering = false; });
      } else {
        this._render(activeWps, lastWps, lat, lon, isRiding, spd);
      }
    }

    _render(wps, lastWps, lat, lon, isRiding, spd) {
      const L   = window.L;
      const map = this._map;
      if (!L || !map) return;

      this._layers.forEach(l => map.removeLayer(l));
      this._layers = [];

      const bounds   = L.latLngBounds();
      const ext      = (la, lo) => bounds.extend([la, lo]);
      const addLayer = l => { l.addTo(map); this._layers.push(l); };

      const tipOpts = { sticky: true, direction: "top", className: "ktm-tooltip" };

      // ── Previous ride (dashed, 45% opacity) ──────────────────────────────
      if (lastWps.length >= 2) {
        for (let i = 0; i < lastWps.length - 1; i++) {
          const [a, b] = [lastWps[i], lastWps[i + 1]];
          const s = ((a[2]||0) + (b[2]||0)) / 2;
          addLayer(L.polyline([[a[0],a[1]],[b[0],b[1]]], {
            color: speedColor(s), weight: 3, opacity: 0.45, dashArray: "6 5", smoothFactor: 1.5,
          }).bindTooltip(`${Math.round(s)} km/h (prev)`, tipOpts));
          ext(a[0],a[1]); ext(b[0],b[1]);
        }
        const ps = lastWps[0], pe = lastWps[lastWps.length - 1];
        addLayer(L.circleMarker([ps[0],ps[1]], { radius:5, color:"#fff", weight:2, fillColor:"#4CAF50", fillOpacity:.7 })
          .bindTooltip("Prev start", tipOpts));
        addLayer(L.circleMarker([pe[0],pe[1]], { radius:5, color:"#fff", weight:2, fillColor:"#888", fillOpacity:.7 })
          .bindTooltip("Prev end", tipOpts));
      }

      // ── Current ride (solid) ──────────────────────────────────────────────
      if (wps.length >= 2) {
        for (let i = 0; i < wps.length - 1; i++) {
          const [a, b] = [wps[i], wps[i + 1]];
          const s = ((a[2]||0) + (b[2]||0)) / 2;
          addLayer(L.polyline([[a[0],a[1]],[b[0],b[1]]], {
            color: speedColor(s), weight: 5, opacity: 0.9, smoothFactor: 1.5,
          }).bindTooltip(`${Math.round(s)} km/h`, tipOpts));
          ext(a[0],a[1]); ext(b[0],b[1]);
        }
        const s0 = wps[0];
        addLayer(L.circleMarker([s0[0],s0[1]], { radius:7, color:"#fff", weight:2, fillColor:"#4CAF50", fillOpacity:1 })
          .bindTooltip("Start", tipOpts));
      }

      // ── Bike marker ───────────────────────────────────────────────────────
      if (lat !== null && !isNaN(lat) && lon !== null && !isNaN(lon)) {
        const col = isRiding ? "#FF6600" : "#2196F3";
        const pulseHtml = isRiding
          ? `<div style="position:absolute;inset:-6px;border-radius:50%;
               background:${col};opacity:.3;animation:ktmpulse 1.5s ease-in-out infinite"></div>`
          : "";
        const icon = L.divIcon({
          className: "",
          html: `<style>
              @keyframes ktmpulse{0%,100%{transform:scale(1)}50%{transform:scale(1.6)}}
            </style>
            <div style="position:relative;width:36px;height:36px">
              ${pulseHtml}
              <div style="position:relative;width:36px;height:36px;border-radius:50%;
                background:${col};border:3px solid #fff;
                display:flex;align-items:center;justify-content:center;
                font-size:18px;box-shadow:0 2px 8px rgba(0,0,0,.6)">🏍</div>
            </div>`,
          iconSize: [36, 36], iconAnchor: [18, 18],
        });
        const label = isRiding ? `🏍 Riding · ${spd.toFixed(0)} km/h` : "🏍 Parked";
        addLayer(L.marker([lat, lon], { icon, zIndexOffset: 1000 })
          .bindTooltip(label, { ...tipOpts, permanent: false, offset: [0, -22] }));
        ext(lat, lon);
      }

      // ── Fit map ───────────────────────────────────────────────────────────
      if (bounds.isValid()) {
        try { map.fitBounds(bounds, { padding: [48, 48], maxZoom: 17 }); }
        catch (_) { if (lat != null) map.setView([lat, lon], 15); }
      } else if (lat != null && !isNaN(lat)) {
        map.setView([lat, lon], 15);
      }

      // Flush tile renderer
      requestAnimationFrame(() => this._map && this._map.invalidateSize(false));
    }
  }

  if (!customElements.get("ktm-route-card")) {
    customElements.define("ktm-route-card", KtmRouteCard);
  }
})();
