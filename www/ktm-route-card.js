/**
 * KTM Route Card – v5
 * Features: no shadow DOM, trip selector (current/last/today/history),
 *           HA visual card editor, motorcycle marker, speed heatmap.
 */
(function () {
  "use strict";

  // ── Constants ────────────────────────────────────────────────────────────

  const LEAFLET_CSS = "/local/leaflet/leaflet.min.css";
  const LEAFLET_JS  = "/local/leaflet/leaflet.min.js";

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

  // ── Leaflet loader ────────────────────────────────────────────────────────

  let _leafletReady = null;
  function loadLeaflet() {
    if (_leafletReady) return _leafletReady;
    _leafletReady = new Promise((resolve, reject) => {
      if (window.L) { resolve(window.L); return; }
      if (!document.querySelector(`link[href="${LEAFLET_CSS}"]`)) {
        const link = document.createElement("link");
        link.rel = "stylesheet"; link.href = LEAFLET_CSS;
        document.head.appendChild(link);
      }
      const s = document.createElement("script");
      s.src = LEAFLET_JS;
      s.onload  = () => resolve(window.L);
      s.onerror = () => reject(new Error("Cannot load Leaflet from " + LEAFLET_JS));
      document.head.appendChild(s);
    });
    return _leafletReady;
  }

  // ── Global card styles (injected once) ───────────────────────────────────

  let _stylesInjected = false;
  function injectStyles() {
    if (_stylesInjected) return;
    _stylesInjected = true;
    const s = document.createElement("style");
    s.textContent = `
      .ktm-header {
        display: flex; align-items: center; justify-content: space-between;
        padding: 12px 16px 6px;
        font-size: 1rem; font-weight: 500;
        color: var(--primary-text-color, #e0e0e0);
      }
      .ktm-badge {
        font-size: .7rem; font-weight: 700; padding: 3px 10px;
        border-radius: 12px; text-transform: uppercase; letter-spacing: .05em;
        flex-shrink: 0;
      }
      .ktm-badge-riding { background: #FF6600; color: #fff; }
      .ktm-badge-parked { background: #444;    color: #bbb; }

      /* ── Trip selector toolbar ── */
      .ktm-toolbar {
        display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
        padding: 0 12px 8px;
      }
      .ktm-btn {
        font-size: .75rem; font-weight: 600; padding: 4px 12px;
        border-radius: 20px; border: 1.5px solid #555; background: transparent;
        color: var(--primary-text-color, #e0e0e0); cursor: pointer;
        transition: background .15s, border-color .15s;
        white-space: nowrap;
      }
      .ktm-btn:hover  { background: rgba(255,102,0,.12); border-color: #FF6600; }
      .ktm-btn.active { background: #FF6600; border-color: #FF6600; color: #fff; }
      .ktm-btn.disabled { opacity: .4; cursor: default; }

      /* ── History dropdown ── */
      .ktm-history-wrap { position: relative; }
      .ktm-history-dropdown {
        position: absolute; top: calc(100% + 4px); left: 0; z-index: 9999;
        background: var(--ha-card-background, #1e1e1e);
        border: 1px solid #444; border-radius: 8px; min-width: 220px;
        box-shadow: 0 4px 16px rgba(0,0,0,.5); overflow: hidden;
      }
      .ktm-history-dropdown.hidden { display: none; }
      .ktm-history-item {
        padding: 9px 14px; cursor: pointer; font-size: .8rem;
        color: var(--primary-text-color, #e0e0e0);
        border-bottom: 1px solid #333;
        display: flex; justify-content: space-between; align-items: center;
      }
      .ktm-history-item:last-child { border-bottom: none; }
      .ktm-history-item:hover { background: rgba(255,102,0,.1); }
      .ktm-history-item.active { background: rgba(255,102,0,.2); color: #FF6600; }
      .ktm-history-dist { font-size: .7rem; color: #888; margin-left: 8px; flex-shrink: 0; }

      /* ── Map ── */
      .ktm-map-wrap { width: 100%; background: #1a1a2e; }

      /* ── Stats bar ── */
      .ktm-stats { display: flex; border-top: 1px solid #333; }
      .ktm-stat  { flex: 1; text-align: center; padding: 8px 4px; }
      .ktm-stat-label { font-size: .62rem; color: #888; text-transform: uppercase; letter-spacing: .04em; }
      .ktm-stat-value { font-size: .92rem; font-weight: 600; color: var(--primary-text-color, #e0e0e0); }

      /* ── Speed legend ── */
      .ktm-legend { display: flex; height: 4px; }
      .ktm-legend-seg { flex: 1; }

      /* ── Leaflet tooltip ── */
      .ktm-tip {
        background: rgba(0,0,0,.82) !important; color: #fff !important;
        border: none !important; font-size: .78rem; padding: 3px 7px;
        border-radius: 4px; box-shadow: 0 1px 4px rgba(0,0,0,.45) !important;
      }
      .ktm-tip::before { display: none !important; }
    `;
    document.head.appendChild(s);
  }

  // ── Helpers ───────────────────────────────────────────────────────────────

  function fmtTs(ts) {
    if (!ts) return "?";
    const d = new Date(ts * 1000);
    const now = new Date();
    const pad = n => String(n).padStart(2, "0");
    const hm = `${pad(d.getHours())}:${pad(d.getMinutes())}`;
    if (d.toDateString() === now.toDateString()) return hm;
    const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    return `${months[d.getMonth()]} ${d.getDate()} ${hm}`;
  }

  function todayMidnight() {
    const d = new Date(); d.setHours(0,0,0,0); return d.getTime() / 1000;
  }

  // ── OSRM road snapping ────────────────────────────────────────────────────

  async function snapToRoads(wps) {
    const out = [];
    for (let i = 0; i < wps.length; i += 95) {
      const batch  = wps.slice(i, i + 95);
      const coords = batch.map(w => `${w[1]},${w[0]}`).join(";");
      try {
        const r = await fetch(
          `https://router.project-osrm.org/match/v1/driving/${coords}?overview=full&geometries=geojson`
        );
        if (!r.ok) throw 0;
        const d = await r.json();
        if (d.matchings?.[0]) {
          d.matchings[0].geometry.coordinates.forEach((c, idx) =>
            out.push([c[1], c[0], batch[Math.min(idx, batch.length - 1)][2]]));
        } else batch.forEach(w => out.push(w));
      } catch (_) { batch.forEach(w => out.push(w)); }
    }
    return out;
  }

  // ════════════════════════════════════════════════════════════════════════
  // Card editor (shown in the HA "pick a card" visual editor)
  // ════════════════════════════════════════════════════════════════════════

  class KtmRouteCardEditor extends HTMLElement {
    _config = {};

    setConfig(config) {
      this._config = { ...config };
      this._render();
    }

    _render() {
      const cfg = this._config;
      this.innerHTML = `
        <div style="padding:16px;display:flex;flex-direction:column;gap:12px">
          <div>
            <div style="font-size:.8rem;color:#888;margin-bottom:4px">Entity (ride track sensor)</div>
            <input id="e-entity" value="${cfg.entity || ""}"
              placeholder="sensor.ktm_390_adv_ride_track"
              style="width:100%;padding:8px;border:1px solid #555;border-radius:6px;
                     background:var(--ha-card-background,#1e1e1e);color:inherit;box-sizing:border-box">
          </div>
          <div>
            <div style="font-size:.8rem;color:#888;margin-bottom:4px">Card title</div>
            <input id="e-title" value="${cfg.title || "KTM 390 ADV Route"}"
              style="width:100%;padding:8px;border:1px solid #555;border-radius:6px;
                     background:var(--ha-card-background,#1e1e1e);color:inherit;box-sizing:border-box">
          </div>
          <div>
            <div style="font-size:.8rem;color:#888;margin-bottom:4px">Default view on load</div>
            <select id="e-view" style="width:100%;padding:8px;border:1px solid #555;border-radius:6px;
                     background:var(--ha-card-background,#1e1e1e);color:inherit">
              <option value="last"    ${(cfg.default_view||"last")==="last"    ? "selected" : ""}>Last ride</option>
              <option value="current" ${cfg.default_view==="current"           ? "selected" : ""}>Current ride</option>
              <option value="today"   ${cfg.default_view==="today"             ? "selected" : ""}>Today (all trips)</option>
            </select>
          </div>
          <div>
            <div style="font-size:.8rem;color:#888;margin-bottom:4px">Map height (px)</div>
            <input id="e-height" type="number" value="${cfg.map_height || 400}"
              style="width:100%;padding:8px;border:1px solid #555;border-radius:6px;
                     background:var(--ha-card-background,#1e1e1e);color:inherit;box-sizing:border-box">
          </div>
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer;font-size:.85rem">
            <input type="checkbox" id="e-snap" ${cfg.snap_to_roads ? "checked" : ""}>
            Snap route to roads (OSRM — needs internet)
          </label>
        </div>`;

      const fire = () => {
        this.dispatchEvent(new CustomEvent("config-changed", {
          detail: {
            config: {
              ...this._config,
              entity:       this.querySelector("#e-entity").value.trim(),
              title:        this.querySelector("#e-title").value.trim(),
              default_view: this.querySelector("#e-view").value,
              map_height:   parseInt(this.querySelector("#e-height").value) || 400,
              snap_to_roads: this.querySelector("#e-snap").checked,
            }
          },
          bubbles: true, composed: true,
        }));
      };

      ["#e-entity","#e-title","#e-height"].forEach(id =>
        this.querySelector(id).addEventListener("change", fire));
      ["#e-view","#e-snap"].forEach(id =>
        this.querySelector(id).addEventListener("change", fire));
    }
  }
  customElements.define("ktm-route-card-editor", KtmRouteCardEditor);

  // ════════════════════════════════════════════════════════════════════════
  // Main card
  // ════════════════════════════════════════════════════════════════════════

  class KtmRouteCard extends HTMLElement {
    constructor() {
      super();
      this._hass      = null;
      this._config    = {};
      this._map       = null;
      this._layers    = [];
      this._lastKey   = "";
      this._built     = false;
      this._rendering = false;
      this._view      = "last";   // "current" | "last" | "today" | "trip:N"
      this._dropOpen  = false;
    }

    // ── HA card protocol ────────────────────────────────────────────────

    static getConfigElement() { return document.createElement("ktm-route-card-editor"); }
    static getStubConfig() {
      return {
        entity:       "sensor.ktm_390_adv_ride_track",
        title:        "KTM 390 ADV Route",
        default_view: "last",
        map_height:   400,
        snap_to_roads: false,
      };
    }

    setConfig(config) {
      this._config = { title: "KTM 390 ADV Route", default_view: "last",
                       map_height: 400, snap_to_roads: false, ...config };
      this._view = this._config.default_view || "last";
    }

    set hass(h) {
      this._hass = h;
      if (!this._built) this._build();
      else this._tryUpdate();
    }

    getCardSize() { return 8; }

    connectedCallback() {
      if (this._map) setTimeout(() => this._map && this._map.invalidateSize(true), 250);
    }

    disconnectedCallback() {
      if (this._ro) { this._ro.disconnect(); this._ro = null; }
    }

    // ── Build DOM ────────────────────────────────────────────────────────

    _build() {
      this._built = true;
      injectStyles();

      const h = this._config.map_height || 400;
      this.innerHTML = `
        <ha-card style="overflow:hidden">
          <div class="ktm-header">
            <span>${this._config.title}</span>
            <span class="ktm-badge ktm-badge-parked" id="ktm-badge">Parked</span>
          </div>
          <div class="ktm-toolbar" id="ktm-toolbar">
            <button class="ktm-btn" data-view="current" id="btn-current">Current</button>
            <button class="ktm-btn active" data-view="last" id="btn-last">Last Ride</button>
            <button class="ktm-btn" data-view="today" id="btn-today">Today</button>
            <div class="ktm-history-wrap" id="hist-wrap">
              <button class="ktm-btn" id="btn-history">History ▾</button>
              <div class="ktm-history-dropdown hidden" id="hist-drop"></div>
            </div>
          </div>
          <div class="ktm-map-wrap" id="ktm-map" style="height:${h}px"></div>
          <div class="ktm-stats">
            <div class="ktm-stat">
              <div class="ktm-stat-label">Distance</div>
              <div class="ktm-stat-value" id="ktm-dist">—</div>
            </div>
            <div class="ktm-stat">
              <div class="ktm-stat-label">Speed</div>
              <div class="ktm-stat-value" id="ktm-spd">—</div>
            </div>
            <div class="ktm-stat">
              <div class="ktm-stat-label">Points</div>
              <div class="ktm-stat-value" id="ktm-pts">—</div>
            </div>
            <div class="ktm-stat">
              <div class="ktm-stat-label">Max spd</div>
              <div class="ktm-stat-value" id="ktm-maxspd">—</div>
            </div>
          </div>
          <div class="ktm-legend" id="ktm-legend"></div>
        </ha-card>`;

      // Speed legend
      const legend = this.querySelector("#ktm-legend");
      SPEED_COLORS.forEach(b => {
        const seg = document.createElement("div");
        seg.className = "ktm-legend-seg";
        seg.style.background = b.color;
        legend.appendChild(seg);
      });

      // Toolbar buttons
      this.querySelectorAll(".ktm-btn[data-view]").forEach(btn => {
        btn.addEventListener("click", () => {
          this._setView(btn.dataset.view);
          this._closeDrop();
        });
      });

      // History dropdown toggle
      this.querySelector("#btn-history").addEventListener("click", (e) => {
        e.stopPropagation();
        this._toggleDrop();
      });

      // Close dropdown on outside click
      document.addEventListener("click", () => this._closeDrop());

      // Init map
      const mapDiv = this.querySelector("#ktm-map");
      loadLeaflet()
        .then(() => this._initMap(mapDiv))
        .catch(err => {
          mapDiv.style.cssText = `display:flex;align-items:center;justify-content:center;
            height:${h}px;color:#aaa;font-size:14px`;
          mapDiv.textContent = "Map failed: " + err.message;
        });
    }

    // ── Toolbar helpers ──────────────────────────────────────────────────

    _setView(view) {
      this._view = view;
      this.querySelectorAll(".ktm-btn[data-view]").forEach(b => {
        b.classList.toggle("active", b.dataset.view === view);
      });
      const histBtn = this.querySelector("#btn-history");
      if (view.startsWith("trip:")) {
        histBtn.classList.add("active");
      } else {
        histBtn.classList.remove("active");
      }
      this._lastKey = "";   // force re-render
      this._tryUpdate();
    }

    _toggleDrop() {
      this._dropOpen = !this._dropOpen;
      const drop = this.querySelector("#hist-drop");
      if (drop) drop.classList.toggle("hidden", !this._dropOpen);
    }

    _closeDrop() {
      this._dropOpen = false;
      const drop = this.querySelector("#hist-drop");
      if (drop) drop.classList.add("hidden");
    }

    _rebuildHistoryDrop(trips) {
      const drop = this.querySelector("#hist-drop");
      if (!drop) return;

      if (!trips || trips.length === 0) {
        drop.innerHTML = `<div class="ktm-history-item" style="color:#888">No trips recorded yet</div>`;
        return;
      }

      // newest first
      const sorted = [...trips].reverse();
      drop.innerHTML = "";

      // Group by day
      let lastDate = "";
      sorted.forEach(trip => {
        const d = trip.start_ts ? new Date(trip.start_ts * 1000) : null;
        const dateStr = d ? d.toLocaleDateString(undefined, {weekday:"short", month:"short", day:"numeric"}) : "Unknown";
        if (dateStr !== lastDate) {
          const sep = document.createElement("div");
          sep.style.cssText = "padding:6px 14px 3px;font-size:.7rem;color:#FF6600;font-weight:700;text-transform:uppercase";
          sep.textContent = dateStr;
          drop.appendChild(sep);
          lastDate = dateStr;
        }

        const item = document.createElement("div");
        item.className = "ktm-history-item" + (this._view === `trip:${trip.id}` ? " active" : "");
        const start = fmtTs(trip.start_ts);
        const end   = fmtTs(trip.end_ts);
        item.innerHTML = `<span>${start} → ${end}</span>
          <span class="ktm-history-dist">${trip.distance_km ? trip.distance_km.toFixed(1)+" km" : ""}</span>`;
        item.addEventListener("click", (e) => {
          e.stopPropagation();
          this._setView(`trip:${trip.id}`);
          this._closeDrop();
        });
        drop.appendChild(item);
      });
    }

    // ── Map init ─────────────────────────────────────────────────────────

    _initMap(mapDiv) {
      const L = window.L;
      if (!L || !mapDiv) return;

      delete L.Icon.Default.prototype._getIconUrl;
      L.Icon.Default.mergeOptions({ iconUrl: false, iconRetinaUrl: false, shadowUrl: false });

      this._map = L.map(mapDiv, {
        zoomControl: true, attributionControl: true, preferCanvas: true,
      });

      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19, attribution: "© OpenStreetMap",
        keepBuffer: 4, updateWhenIdle: false, updateWhenZooming: true,
      }).addTo(this._map);

      this._map.setView([12.94, 77.61], 14);

      if (window.ResizeObserver) {
        this._ro = new ResizeObserver(() => this._map && this._map.invalidateSize(true));
        this._ro.observe(mapDiv);
      }

      requestAnimationFrame(() => requestAnimationFrame(() => {
        if (!this._map) return;
        this._map.invalidateSize(true);
        this._tryUpdate();
      }));
    }

    // ── Entity helpers ───────────────────────────────────────────────────

    _tryUpdate() {
      if (this._map && this._hass) this._updateCard();
    }

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

    // ── Main update ──────────────────────────────────────────────────────

    _updateCard() {
      if (this._rendering) return;

      const entity  = this._getEntity();
      const tracker = this._getTracker();

      const isRiding   = entity?.state === "riding";
      const attrs      = entity?.attributes || {};
      const wps        = attrs.waypoints            || [];
      const lastWps    = attrs.last_ride_waypoints  || [];
      const trips      = attrs.trip_history         || [];
      const dist       = attrs.ride_distance_km     || 0;
      const ptCount    = attrs.waypoint_count       || wps.length;

      const ta  = tracker?.attributes || {};
      const lat = ta.latitude  != null ? parseFloat(ta.latitude)  : null;
      const lon = ta.longitude != null ? parseFloat(ta.longitude) : null;
      const spd = parseFloat(ta.speed_kmh || 0);

      // Rebuild history dropdown on trips change
      const tripsKey = trips.length + (trips[trips.length-1]?.id || 0);
      if (tripsKey !== this._lastTripsKey) {
        this._lastTripsKey = tripsKey;
        this._rebuildHistoryDrop(trips);
      }

      // Determine which waypoints to display based on current view
      let displayWps = [];
      let displayDist = 0;
      let displayMaxSpd = 0;

      if (this._view === "current") {
        displayWps  = isRiding ? wps : [];
        displayDist = isRiding ? dist : 0;
      } else if (this._view === "last") {
        displayWps  = lastWps;
        displayDist = lastWps.length > 0
          ? this._calcDist(lastWps) : 0;
      } else if (this._view === "today") {
        const midnight = todayMidnight();
        const todayTrips = trips.filter(t => (t.start_ts || 0) >= midnight);
        displayWps  = todayTrips.flatMap(t => t.waypoints || []);
        displayDist = todayTrips.reduce((s, t) => s + (t.distance_km || 0), 0);
      } else if (this._view.startsWith("trip:")) {
        const id   = parseInt(this._view.split(":")[1]);
        const trip = trips.find(t => t.id === id);
        displayWps  = trip?.waypoints || [];
        displayDist = trip?.distance_km || 0;
        displayMaxSpd = trip?.max_speed || 0;
      }

      if (displayWps.length > 0) {
        displayMaxSpd = displayMaxSpd || Math.max(...displayWps.map(w => w[2] || 0));
      }

      const key = `${this._view}|${isRiding}|${ptCount}|${trips.length}|${lat}|${lon}|${spd}`;
      if (key === this._lastKey) return;
      this._lastKey = key;

      // Badge
      const badge = this.querySelector("#ktm-badge");
      if (badge) {
        badge.textContent = isRiding ? "Riding" : "Parked";
        badge.className   = isRiding ? "ktm-badge ktm-badge-riding" : "ktm-badge ktm-badge-parked";
      }

      // Update "Current" button availability
      const btnCur = this.querySelector("#btn-current");
      if (btnCur) btnCur.classList.toggle("disabled", !isRiding);

      // Stats
      const q = id => this.querySelector("#" + id);
      const sd = q("ktm-dist"), ss = q("ktm-spd"), sp = q("ktm-pts"), sm = q("ktm-maxspd");
      if (sd) sd.textContent = displayDist ? `${displayDist.toFixed(2)} km` : "—";
      if (ss) ss.textContent = spd > 0 ? `${spd.toFixed(0)} km/h` : "—";
      if (sp) sp.textContent = displayWps.length || "—";
      if (sm) sm.textContent = displayMaxSpd > 0 ? `${displayMaxSpd.toFixed(0)} km/h` : "—";

      if (this._config.snap_to_roads && displayWps.length >= 2) {
        this._rendering = true;
        snapToRoads(displayWps)
          .then(s  => this._render(s, lat, lon, isRiding, spd))
          .catch(() => this._render(displayWps, lat, lon, isRiding, spd))
          .finally(() => { this._rendering = false; });
      } else {
        this._render(displayWps, lat, lon, isRiding, spd);
      }
    }

    _calcDist(wps) {
      let d = 0;
      for (let i = 1; i < wps.length; i++) {
        const [a, b] = [wps[i-1], wps[i]];
        const R = 6371, dLat = (b[0]-a[0]) * Math.PI/180, dLon = (b[1]-a[1]) * Math.PI/180;
        const x = Math.sin(dLat/2)**2 + Math.cos(a[0]*Math.PI/180)*Math.cos(b[0]*Math.PI/180)*Math.sin(dLon/2)**2;
        d += R * 2 * Math.atan2(Math.sqrt(x), Math.sqrt(1-x));
      }
      return Math.round(d * 100) / 100;
    }

    // ── Render route + marker ────────────────────────────────────────────

    _render(wps, lat, lon, isRiding, spd) {
      const L   = window.L;
      const map = this._map;
      if (!L || !map) return;

      this._layers.forEach(l => map.removeLayer(l));
      this._layers = [];

      const bounds   = L.latLngBounds();
      const ext      = (la, lo) => bounds.extend([la, lo]);
      const addLayer = l => { l.addTo(map); this._layers.push(l); };
      const tipOpts  = { sticky: true, direction: "top", className: "ktm-tip" };

      // Route polylines (speed-colored)
      if (wps.length >= 2) {
        for (let i = 0; i < wps.length - 1; i++) {
          const [a, b] = [wps[i], wps[i + 1]];
          const s = ((a[2]||0) + (b[2]||0)) / 2;
          addLayer(L.polyline([[a[0],a[1]],[b[0],b[1]]], {
            color: speedColor(s), weight: 5, opacity: 0.9,
          }).bindTooltip(`${Math.round(s)} km/h`, tipOpts));
          ext(a[0],a[1]); ext(b[0],b[1]);
        }
        // Start dot
        const s0 = wps[0];
        addLayer(L.circleMarker([s0[0],s0[1]],
          { radius:7, color:"#fff", weight:2, fillColor:"#4CAF50", fillOpacity:1 })
          .bindTooltip("Start", tipOpts));
        // End dot (for historical, not current)
        if (!isRiding || this._view !== "current") {
          const sN = wps[wps.length-1];
          addLayer(L.circleMarker([sN[0],sN[1]],
            { radius:7, color:"#fff", weight:2, fillColor:"#E53935", fillOpacity:1 })
            .bindTooltip("End", tipOpts));
        }
      }

      // Bike marker — always shown when GPS valid
      if (lat !== null && !isNaN(lat) && lon !== null && !isNaN(lon)) {
        const col = isRiding ? "#FF6600" : "#2196F3";
        const pulseCss = isRiding
          ? `position:absolute;inset:-6px;border-radius:50%;background:${col};opacity:.3;animation:ktmpulse 1.5s ease-in-out infinite`
          : `display:none`;
        const icon = L.divIcon({
          className: "",
          html: `<style>@keyframes ktmpulse{0%,100%{transform:scale(1)}50%{transform:scale(1.6)}}</style>
                 <div style="position:relative;width:36px;height:36px">
                   <div style="${pulseCss}"></div>
                   <div style="position:relative;width:36px;height:36px;border-radius:50%;
                     background:${col};border:3px solid #fff;
                     display:flex;align-items:center;justify-content:center;
                     font-size:18px;box-shadow:0 2px 8px rgba(0,0,0,.6)">🏍</div>
                 </div>`,
          iconSize: [36, 36], iconAnchor: [18, 18],
        });
        addLayer(L.marker([lat, lon], { icon, zIndexOffset: 1000 })
          .bindTooltip(isRiding ? `🏍 ${spd.toFixed(0)} km/h` : "🏍 Parked",
            { ...tipOpts, permanent: false, offset: [0, -22] }));
        ext(lat, lon);
      }

      // Fit map
      if (bounds.isValid()) {
        try { map.fitBounds(bounds, { padding: [40, 40], maxZoom: 17 }); }
        catch (_) { if (lat != null) map.setView([lat, lon], 15); }
      } else if (lat !== null && !isNaN(lat)) {
        map.setView([lat, lon], 15);
      }

      requestAnimationFrame(() => this._map && this._map.invalidateSize(false));
    }
  }

  if (!customElements.get("ktm-route-card")) {
    customElements.define("ktm-route-card", KtmRouteCard);
  }
})();
