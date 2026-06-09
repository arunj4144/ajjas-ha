/**
 * KTM Route Card – Custom Lovelace card for Ajjas / KTM 390 ADV
 * v2 – fixed tile loading, 1:1 ratio, bike marker, previous ride path
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
    for (const band of SPEED_COLORS) {
      if (s <= band.max) return band.color;
    }
    return "#F44336";
  }

  // Leaflet loader — injects JS + CSS into document.head once
  const LEAFLET_CSS = "/local/leaflet/leaflet.min.css";
  const LEAFLET_JS  = "/local/leaflet/leaflet.min.js";
  let _leafletReady = null;

  function loadLeaflet() {
    if (_leafletReady) return _leafletReady;
    _leafletReady = new Promise((resolve, reject) => {
      if (window.L) { resolve(window.L); return; }

      // CSS into document.head so Leaflet's internal image paths work
      if (!document.querySelector(`link[href="${LEAFLET_CSS}"]`)) {
        const link = document.createElement("link");
        link.rel = "stylesheet";
        link.href = LEAFLET_CSS;
        document.head.appendChild(link);
      }

      const script = document.createElement("script");
      script.src = LEAFLET_JS;
      script.onload = () => resolve(window.L);
      script.onerror = () => reject(new Error("Leaflet failed to load from " + LEAFLET_JS));
      document.head.appendChild(script);
    });
    return _leafletReady;
  }

  // OSRM road-snap helper (batches of 95)
  async function snapToRoads(waypoints) {
    const BATCH = 95;
    const snapped = [];
    for (let i = 0; i < waypoints.length; i += BATCH) {
      const batch = waypoints.slice(i, i + BATCH);
      const coords = batch.map(w => `${w[1]},${w[0]}`).join(";");
      const url = `https://router.project-osrm.org/match/v1/driving/${coords}?overview=full&geometries=geojson`;
      try {
        const resp = await fetch(url);
        if (!resp.ok) throw new Error();
        const data = await resp.json();
        if (data.matchings && data.matchings.length) {
          data.matchings[0].geometry.coordinates.forEach((c, idx) => {
            snapped.push([c[1], c[0], batch[Math.min(idx, batch.length - 1)][2]]);
          });
        } else {
          batch.forEach(w => snapped.push(w));
        }
      } catch (_) {
        batch.forEach(w => snapped.push(w));
      }
    }
    return snapped;
  }

  class KtmRouteCard extends HTMLElement {
    constructor() {
      super();
      this._hass = null;
      this._config = {};
      this._map = null;
      this._tileLayer = null;
      this._layers = [];
      this._resizeObserver = null;
      this._lastKey = "";
      this._rendering = false;
      this.attachShadow({ mode: "open" });
    }

    // ── Lovelace lifecycle ──────────────────────────────────────────────────

    setConfig(config) {
      this._config = { title: "KTM 390 ADV Route", snap_to_roads: false, ...config };
      this._build();
    }

    set hass(hass) {
      this._hass = hass;
      this._updateCard();
    }

    getCardSize() { return 8; }

    connectedCallback() {
      // Re-validate size when card is attached/re-attached to DOM
      if (this._map) {
        requestAnimationFrame(() => this._map && this._map.invalidateSize(true));
      }
    }

    disconnectedCallback() {
      if (this._resizeObserver) { this._resizeObserver.disconnect(); this._resizeObserver = null; }
    }

    // ── Shadow DOM construction ─────────────────────────────────────────────

    _build() {
      const title = this._config.title || "KTM 390 ADV Route";

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
        .badge {
          font-size: 0.72rem; font-weight: 700; padding: 3px 10px;
          border-radius: 12px; text-transform: uppercase; letter-spacing: 0.05em;
        }
        .badge-riding { background: #FF6600; color: #fff; }
        .badge-parked { background: #555; color: #ccc; }

        /* 1:1 square map via aspect-ratio */
        #map-wrap {
          width: 100%;
          aspect-ratio: 1 / 1;
          position: relative;
          background: #1a1a2e;
        }
        #map {
          position: absolute; inset: 0;
          width: 100% !important;
          height: 100% !important;
        }

        .stats-bar {
          display: flex;
          background: var(--ha-card-background, #1c1c1e);
          border-top: 1px solid var(--divider-color, #333);
        }
        .stat { flex: 1; text-align: center; padding: 8px 4px; }
        .stat-label { font-size: 0.65rem; color: var(--secondary-text-color, #aaa); text-transform: uppercase; letter-spacing: 0.04em; }
        .stat-value { font-size: 0.95rem; font-weight: 600; color: var(--primary-text-color, #fff); }
        .speed-legend { display: flex; height: 5px; }
        .speed-legend-seg { flex: 1; }
      `;

      const card = document.createElement("ha-card");

      const header = document.createElement("div");
      header.className = "card-header";
      header.innerHTML = `<span>${title}</span><span class="badge badge-parked" id="riding-badge">Parked</span>`;

      const mapWrap = document.createElement("div");
      mapWrap.id = "map-wrap";
      const mapDiv = document.createElement("div");
      mapDiv.id = "map";
      mapWrap.appendChild(mapDiv);

      const statsBar = document.createElement("div");
      statsBar.className = "stats-bar";
      statsBar.innerHTML = `
        <div class="stat"><div class="stat-label">Distance</div><div class="stat-value" id="stat-dist">—</div></div>
        <div class="stat"><div class="stat-label">Speed</div><div class="stat-value" id="stat-spd">—</div></div>
        <div class="stat"><div class="stat-label">Points</div><div class="stat-value" id="stat-pts">—</div></div>
      `;

      const legend = document.createElement("div");
      legend.className = "speed-legend";
      SPEED_COLORS.forEach(band => {
        const seg = document.createElement("div");
        seg.className = "speed-legend-seg";
        seg.style.background = band.color;
        legend.appendChild(seg);
      });

      card.appendChild(header);
      card.appendChild(mapWrap);
      card.appendChild(statsBar);
      card.appendChild(legend);

      this.shadowRoot.innerHTML = "";
      this.shadowRoot.appendChild(style);
      this.shadowRoot.appendChild(card);

      this._mapDiv = mapDiv;
      this._map = null;
      this._layers = [];

      loadLeaflet()
        .then(() => this._initMap())
        .catch(err => {
          mapWrap.innerHTML = `<div style="display:flex;align-items:center;justify-content:center;width:100%;height:100%;color:#aaa;font-size:.9rem">${err.message}</div>`;
        });
    }

    _initMap() {
      const L = window.L;
      if (!L || !this._mapDiv) return;

      // Suppress default icon path errors in shadow DOM
      delete L.Icon.Default.prototype._getIconUrl;
      L.Icon.Default.mergeOptions({ iconUrl: false, iconRetinaUrl: false, shadowUrl: false });

      this._map = L.map(this._mapDiv, {
        zoomControl: true,
        attributionControl: false,
        preferCanvas: true,
      });

      this._tileLayer = L.tileLayer(
        "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        { maxZoom: 19, keepBuffer: 4, updateWhenIdle: false, updateWhenZooming: true }
      ).addTo(this._map);

      L.control.attribution({ prefix: false, position: "bottomright" })
        .addAttribution("© OpenStreetMap")
        .addTo(this._map);

      this._map.setView([12.94, 77.61], 14);

      // ResizeObserver: recalculate tiles whenever the container is resized
      if (window.ResizeObserver) {
        this._resizeObserver = new ResizeObserver(() => {
          if (this._map) this._map.invalidateSize(true);
        });
        this._resizeObserver.observe(this._mapDiv);
      }

      // Wait two frames so the shadow DOM has painted and aspect-ratio is resolved
      requestAnimationFrame(() => requestAnimationFrame(() => {
        if (this._map) {
          this._map.invalidateSize(true);
          this._updateCard();
        }
      }));
    }

    // ── Data helpers ────────────────────────────────────────────────────────

    _resolveEntity() {
      if (!this._hass) return null;
      if (this._config.entity) return this._hass.states[this._config.entity] || null;
      const key = Object.keys(this._hass.states).find(
        k => k.startsWith("sensor.") && k.includes("ride_track")
      );
      return key ? this._hass.states[key] : null;
    }

    _resolveTracker() {
      if (!this._hass) return null;
      const key = Object.keys(this._hass.states).find(
        k => k.startsWith("device_tracker.") && (k.includes("ktm") || k.includes("ajjas"))
      );
      return key ? this._hass.states[key] : null;
    }

    // ── Card update ─────────────────────────────────────────────────────────

    _updateCard() {
      if (!this._map || !this._hass) return;
      if (this._rendering) return;

      const entity  = this._resolveEntity();
      const tracker = this._resolveTracker();

      const isRiding      = entity ? entity.state === "riding" : false;
      const attrs         = entity ? entity.attributes || {} : {};
      const waypoints     = attrs.waypoints || [];
      const lastWaypoints = attrs.last_ride_waypoints || [];
      const rideDist      = attrs.ride_distance_km || 0;
      const ptCount       = attrs.waypoint_count || waypoints.length;

      const trackerAttrs = tracker ? tracker.attributes || {} : {};
      const lat   = trackerAttrs.latitude  != null ? parseFloat(trackerAttrs.latitude)  : null;
      const lon   = trackerAttrs.longitude != null ? parseFloat(trackerAttrs.longitude) : null;
      const speed = parseFloat(trackerAttrs.speed_kmh || 0);

      // Build a cheap change-detection key
      const key = `${isRiding}|${ptCount}|${lastWaypoints.length}|${lat}|${lon}`;
      if (key === this._lastKey) return;
      this._lastKey = key;

      // Badge
      const badge = this.shadowRoot.getElementById("riding-badge");
      if (badge) {
        badge.textContent = isRiding ? "Riding" : "Parked";
        badge.className   = isRiding ? "badge badge-riding" : "badge badge-parked";
      }

      // Stats bar
      const sd = this.shadowRoot.getElementById("stat-dist");
      const ss = this.shadowRoot.getElementById("stat-spd");
      const sp = this.shadowRoot.getElementById("stat-pts");
      if (sd) sd.textContent = rideDist ? rideDist.toFixed(2) + " km" : (lastWaypoints.length ? "prev ride" : "—");
      if (ss) ss.textContent = isRiding ? speed.toFixed(0) + " km/h" : "—";
      if (sp) sp.textContent = ptCount || (lastWaypoints.length ? lastWaypoints.length + " prev" : "—");

      // Route rendering
      const activeWpts = isRiding ? waypoints : [];

      if (this._config.snap_to_roads && activeWpts.length >= 2) {
        this._rendering = true;
        snapToRoads(activeWpts)
          .then(snapped => this._renderAll(snapped, lastWaypoints, lat, lon, isRiding, speed))
          .catch(()     => this._renderAll(activeWpts, lastWaypoints, lat, lon, isRiding, speed))
          .finally(()   => { this._rendering = false; });
      } else {
        this._renderAll(activeWpts, lastWaypoints, lat, lon, isRiding, speed);
      }
    }

    _renderAll(waypoints, lastWaypoints, lat, lon, isRiding, speed) {
      const L   = window.L;
      const map = this._map;
      if (!L || !map) return;

      // Clear existing layers
      this._layers.forEach(l => map.removeLayer(l));
      this._layers = [];

      const bounds = L.latLngBounds();
      let hasBounds = false;

      const extendBounds = (la, lo) => { bounds.extend([la, lo]); hasBounds = true; };

      // ── Previous ride path (dashed, semi-transparent) ──────────────────
      if (lastWaypoints.length >= 2) {
        for (let i = 0; i < lastWaypoints.length - 1; i++) {
          const a = lastWaypoints[i], b = lastWaypoints[i + 1];
          const spd = ((a[2] || 0) + (b[2] || 0)) / 2;
          const seg = L.polyline([[a[0], a[1]], [b[0], b[1]]], {
            color: speedColor(spd), weight: 3, opacity: 0.45,
            dashArray: "6 5", smoothFactor: 1.5,
          }).bindTooltip(`${Math.round(spd)} km/h (prev ride)`, { sticky: true, direction: "top" });
          seg.addTo(map);
          this._layers.push(seg);
          extendBounds(a[0], a[1]);
          extendBounds(b[0], b[1]);
        }
        // Previous ride start / end markers
        const pStart = lastWaypoints[0];
        const pEnd   = lastWaypoints[lastWaypoints.length - 1];
        [
          { pt: pStart, fill: "#4CAF50", label: "Prev start" },
          { pt: pEnd,   fill: "#888",    label: "Prev end"   },
        ].forEach(({ pt, fill, label }) => {
          const m = L.circleMarker([pt[0], pt[1]], {
            radius: 5, color: "#fff", weight: 2, fillColor: fill, fillOpacity: 0.7,
          }).bindTooltip(label, { direction: "top" });
          m.addTo(map);
          this._layers.push(m);
        });
      }

      // ── Current / active ride path (solid, full opacity) ───────────────
      if (waypoints.length >= 2) {
        for (let i = 0; i < waypoints.length - 1; i++) {
          const a = waypoints[i], b = waypoints[i + 1];
          const spd = ((a[2] || 0) + (b[2] || 0)) / 2;
          const seg = L.polyline([[a[0], a[1]], [b[0], b[1]]], {
            color: speedColor(spd), weight: 5, opacity: 0.9, smoothFactor: 1.5,
          }).bindTooltip(`${Math.round(spd)} km/h`, { sticky: true, direction: "top" });
          seg.addTo(map);
          this._layers.push(seg);
          extendBounds(a[0], a[1]);
          extendBounds(b[0], b[1]);
        }
        // Ride start dot
        const s = waypoints[0];
        const startDot = L.circleMarker([s[0], s[1]], {
          radius: 7, color: "#fff", weight: 2, fillColor: "#4CAF50", fillOpacity: 1,
        }).bindTooltip("Start", { direction: "top" });
        startDot.addTo(map);
        this._layers.push(startDot);
      }

      // ── Bike marker at current GPS position ────────────────────────────
      if (lat !== null && lon !== null && !isNaN(lat) && !isNaN(lon)) {
        const color = isRiding ? "#FF6600" : "#2196F3";
        const pulse = isRiding
          ? `<div style="position:absolute;inset:-6px;border-radius:50%;background:${color};opacity:.25;animation:pulse 1.5s infinite"></div>`
          : "";
        const bikeIcon = L.divIcon({
          className: "",
          html: `
            <style>@keyframes pulse{0%,100%{transform:scale(1)}50%{transform:scale(1.5)}}</style>
            <div style="position:relative;width:36px;height:36px">
              ${pulse}
              <div style="position:relative;width:36px;height:36px;border-radius:50%;background:${color};border:3px solid #fff;display:flex;align-items:center;justify-content:center;font-size:18px;box-shadow:0 2px 8px rgba(0,0,0,.6)">🏍</div>
            </div>`,
          iconSize:   [36, 36],
          iconAnchor: [18, 18],
          popupAnchor:[0, -20],
        });

        const label = isRiding ? `🏍 ${speed.toFixed(0)} km/h` : "🏍 Parked";
        const marker = L.marker([lat, lon], { icon: bikeIcon, zIndexOffset: 1000 })
          .bindTooltip(label, { permanent: false, direction: "top", offset: [0, -20] });
        marker.addTo(map);
        this._layers.push(marker);
        extendBounds(lat, lon);
      }

      // ── Fit map ────────────────────────────────────────────────────────
      if (hasBounds && bounds.isValid()) {
        try {
          map.fitBounds(bounds, { padding: [40, 40], maxZoom: 17 });
        } catch (_) {
          if (lat !== null) map.setView([lat, lon], 15);
        }
      } else if (lat !== null && !isNaN(lat)) {
        map.setView([lat, lon], 15);
      }

      // Force tiles to repaint after layout
      requestAnimationFrame(() => this._map && this._map.invalidateSize(false));
    }
  }

  if (!customElements.get("ktm-route-card")) {
    customElements.define("ktm-route-card", KtmRouteCard);
  }
})();
