/**
 * KTM Route Card – Custom Lovelace element for Ajjas / KTM 390 ADV
 *
 * Displays a live Leaflet map with speed-coloured route segments.
 *
 * Config keys:
 *   entity        – sensor.*ride_track* entity (auto-detected if omitted)
 *   speed_entity  – optional separate speed sensor entity id
 *   height        – map height in px (default 350)
 *   snap_to_roads – boolean, use OSRM map-matching (default false)
 *   title         – card header title (default "KTM 390 ADV Route")
 */

(function () {
  "use strict";

  // -----------------------------------------------------------------------
  // Speed → colour map
  // -----------------------------------------------------------------------
  const SPEED_COLORS = [
    { max: 20, color: "#4CAF50" },
    { max: 40, color: "#8BC34A" },
    { max: 60, color: "#CDDC39" },
    { max: 80, color: "#FFC107" },
    { max: 100, color: "#FF9800" },
    { max: 120, color: "#FF5722" },
    { max: Infinity, color: "#F44336" },
  ];

  function speedColor(spd) {
    const s = parseFloat(spd) || 0;
    for (const band of SPEED_COLORS) {
      if (s <= band.max) return band.color;
    }
    return "#F44336";
  }

  // -----------------------------------------------------------------------
  // Leaflet loader (shared across card instances)
  // -----------------------------------------------------------------------
  const LEAFLET_CSS = "/local/leaflet/leaflet.min.css";
  const LEAFLET_JS = "/local/leaflet/leaflet.min.js";

  let _leafletReady = null;

  function loadLeaflet() {
    if (_leafletReady) return _leafletReady;

    _leafletReady = new Promise((resolve, reject) => {
      if (window.L) {
        resolve(window.L);
        return;
      }

      // Inject JS into document.head once
      const script = document.createElement("script");
      script.src = LEAFLET_JS;
      script.onload = () => resolve(window.L);
      script.onerror = () => reject(new Error("Failed to load Leaflet JS from " + LEAFLET_JS));
      document.head.appendChild(script);
    });

    return _leafletReady;
  }

  // -----------------------------------------------------------------------
  // OSRM map-matching helper
  // -----------------------------------------------------------------------
  async function snapToRoads(waypoints) {
    // waypoints: [[lat, lon, spd], ...]
    // OSRM match expects [lon,lat] and max 100 coords – use batches of 95
    const BATCH = 95;
    const snapped = [];

    for (let i = 0; i < waypoints.length; i += BATCH) {
      const batch = waypoints.slice(i, i + BATCH);
      const coords = batch.map((w) => `${w[1]},${w[0]}`).join(";");
      const url =
        `https://router.project-osrm.org/match/v1/driving/${coords}` +
        `?overview=full&geometries=geojson&annotations=false`;

      try {
        const resp = await fetch(url);
        if (!resp.ok) throw new Error("OSRM HTTP " + resp.status);
        const data = await resp.json();

        if (data.matchings && data.matchings.length > 0) {
          const coords2 = data.matchings[0].geometry.coordinates; // [lon, lat]
          // Preserve speed from original batch (nearest-neighbour simple approach)
          coords2.forEach((c, idx) => {
            const origIdx = Math.min(idx, batch.length - 1);
            snapped.push([c[1], c[0], batch[origIdx][2]]);
          });
        } else {
          // Fallback: keep originals
          batch.forEach((w) => snapped.push(w));
        }
      } catch (_) {
        batch.forEach((w) => snapped.push(w));
      }
    }

    return snapped;
  }

  // -----------------------------------------------------------------------
  // Custom element
  // -----------------------------------------------------------------------
  class KtmRouteCard extends HTMLElement {
    constructor() {
      super();
      this._hass = null;
      this._config = {};
      this._map = null;
      this._layers = [];
      this._lastWaypointCount = -1;
      this._lastIsRiding = null;
      this._rendering = false;
      this.attachShadow({ mode: "open" });
    }

    // ------------------------------------------------------------------
    // Lovelace lifecycle
    // ------------------------------------------------------------------

    setConfig(config) {
      if (!config) {
        throw new Error("KtmRouteCard: config is required");
      }
      this._config = {
        title: "KTM 390 ADV Route",
        height: 350,
        snap_to_roads: false,
        ...config,
      };
      this._build();
    }

    set hass(hass) {
      this._hass = hass;
      this._updateCard();
    }

    getCardSize() {
      return Math.ceil((this._config.height || 350) / 50);
    }

    // ------------------------------------------------------------------
    // Shadow DOM construction
    // ------------------------------------------------------------------

    _build() {
      const height = this._config.height || 350;
      const title = this._config.title || "KTM 390 ADV Route";

      // Inject Leaflet CSS into shadow root
      const leafletLink = document.createElement("link");
      leafletLink.rel = "stylesheet";
      leafletLink.href = LEAFLET_CSS;

      const style = document.createElement("style");
      style.textContent = `
        :host {
          display: block;
          font-family: var(--primary-font-family, sans-serif);
        }
        ha-card {
          overflow: hidden;
        }
        .card-header {
          display: flex;
          align-items: center;
          justify-content: space-between;
          padding: 12px 16px 8px;
          font-size: 1rem;
          font-weight: 500;
          color: var(--primary-text-color, #fff);
          background: var(--ha-card-background, #1c1c1e);
        }
        .badge {
          font-size: 0.72rem;
          font-weight: 700;
          padding: 3px 10px;
          border-radius: 12px;
          text-transform: uppercase;
          letter-spacing: 0.05em;
        }
        .badge-riding {
          background: #FF6600;
          color: #fff;
        }
        .badge-parked {
          background: #555;
          color: #ccc;
        }
        #map {
          width: 100%;
          height: ${height}px;
        }
        .stats-bar {
          display: flex;
          gap: 0;
          background: var(--ha-card-background, #1c1c1e);
          border-top: 1px solid var(--divider-color, #333);
        }
        .stat {
          flex: 1;
          text-align: center;
          padding: 8px 4px;
        }
        .stat-label {
          font-size: 0.65rem;
          color: var(--secondary-text-color, #aaa);
          text-transform: uppercase;
          letter-spacing: 0.04em;
        }
        .stat-value {
          font-size: 0.95rem;
          font-weight: 600;
          color: var(--primary-text-color, #fff);
        }
        .speed-legend {
          display: flex;
          height: 6px;
        }
        .speed-legend-seg {
          flex: 1;
        }
        .no-data {
          display: flex;
          align-items: center;
          justify-content: center;
          height: ${height}px;
          color: var(--secondary-text-color, #aaa);
          font-size: 0.9rem;
          background: var(--ha-card-background, #1c1c1e);
        }
      `;

      const card = document.createElement("ha-card");

      const header = document.createElement("div");
      header.className = "card-header";
      header.innerHTML = `<span class="card-title">${title}</span><span class="badge badge-parked" id="riding-badge">Parked</span>`;

      const mapDiv = document.createElement("div");
      mapDiv.id = "map";

      const statsBar = document.createElement("div");
      statsBar.className = "stats-bar";
      statsBar.innerHTML = `
        <div class="stat">
          <div class="stat-label">Distance</div>
          <div class="stat-value" id="stat-dist">—</div>
        </div>
        <div class="stat">
          <div class="stat-label">Speed</div>
          <div class="stat-value" id="stat-spd">—</div>
        </div>
        <div class="stat">
          <div class="stat-label">Points</div>
          <div class="stat-value" id="stat-pts">—</div>
        </div>
      `;

      // Speed legend
      const legend = document.createElement("div");
      legend.className = "speed-legend";
      SPEED_COLORS.forEach((band) => {
        const seg = document.createElement("div");
        seg.className = "speed-legend-seg";
        seg.style.background = band.color;
        legend.appendChild(seg);
      });

      card.appendChild(header);
      card.appendChild(mapDiv);
      card.appendChild(statsBar);
      card.appendChild(legend);

      this.shadowRoot.innerHTML = "";
      this.shadowRoot.appendChild(leafletLink);
      this.shadowRoot.appendChild(style);
      this.shadowRoot.appendChild(card);

      this._mapDiv = mapDiv;
      this._map = null;

      loadLeaflet()
        .then(() => this._initMap())
        .catch((err) => {
          mapDiv.innerHTML = `<div class="no-data">Map unavailable: ${err.message}</div>`;
          mapDiv.style.height = (this._config.height || 350) + "px";
          mapDiv.style.display = "flex";
          mapDiv.style.alignItems = "center";
          mapDiv.style.justifyContent = "center";
        });
    }

    _initMap() {
      const L = window.L;
      if (!L || !this._mapDiv) return;

      this._map = L.map(this._mapDiv, {
        zoomControl: true,
        attributionControl: true,
      });

      L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution: "© OpenStreetMap contributors",
      }).addTo(this._map);

      this._map.setView([10.0, 76.5], 12);
      this._updateCard();
    }

    // ------------------------------------------------------------------
    // Data helpers
    // ------------------------------------------------------------------

    _resolveEntity() {
      if (!this._hass) return null;
      const states = this._hass.states;

      // Use configured entity if supplied
      if (this._config.entity) {
        return states[this._config.entity] || null;
      }

      // Auto-detect: find first sensor.*ride_track* entity
      const key = Object.keys(states).find(
        (k) => k.startsWith("sensor.") && k.includes("ride_track")
      );
      return key ? states[key] : null;
    }

    _resolveTracker() {
      if (!this._hass) return null;
      const states = this._hass.states;
      const key = Object.keys(states).find(
        (k) =>
          k.startsWith("device_tracker.") &&
          (k.includes("ktm") || k.includes("ajjas"))
      );
      return key ? states[key] : null;
    }

    _currentSpeed() {
      if (!this._hass) return null;
      if (this._config.speed_entity) {
        const s = this._hass.states[this._config.speed_entity];
        return s ? parseFloat(s.state) || 0 : null;
      }
      const entity = this._resolveEntity();
      if (!entity) return null;
      // Ride track attributes don't carry speed directly; fall back to 0
      return null;
    }

    // ------------------------------------------------------------------
    // Card update
    // ------------------------------------------------------------------

    _updateCard() {
      if (!this._map || !this._hass) return;
      if (this._rendering) return;

      const entity = this._resolveEntity();
      const isRiding = entity
        ? entity.state === "riding"
        : false;

      const attrs = entity ? entity.attributes || {} : {};
      const waypoints = attrs.waypoints || [];
      const lastWaypoints = attrs.last_ride_waypoints || [];
      const rideDist = attrs.ride_distance_km || 0;
      const waypointCount = attrs.waypoint_count || waypoints.length;

      // Avoid unnecessary re-renders
      if (
        waypointCount === this._lastWaypointCount &&
        isRiding === this._lastIsRiding
      ) {
        return;
      }
      this._lastWaypointCount = waypointCount;
      this._lastIsRiding = isRiding;

      // Update header badge
      const badge = this.shadowRoot.getElementById("riding-badge");
      if (badge) {
        badge.textContent = isRiding ? "Riding" : "Parked";
        badge.className = isRiding ? "badge badge-riding" : "badge badge-parked";
      }

      // Update stats bar
      const statDist = this.shadowRoot.getElementById("stat-dist");
      const statSpd = this.shadowRoot.getElementById("stat-spd");
      const statPts = this.shadowRoot.getElementById("stat-pts");

      if (statDist) statDist.textContent = rideDist ? rideDist.toFixed(2) + " km" : "—";
      if (statPts) statPts.textContent = waypointCount || "—";

      // Speed stat
      const speedEntity = this._config.speed_entity
        ? this._hass.states[this._config.speed_entity]
        : null;
      if (statSpd) {
        if (speedEntity) {
          statSpd.textContent =
            parseFloat(speedEntity.state).toFixed(0) +
            " " +
            (speedEntity.attributes.unit_of_measurement || "km/h");
        } else if (waypoints.length > 0) {
          const lastWp = waypoints[waypoints.length - 1];
          statSpd.textContent = (lastWp[2] || 0).toFixed(0) + " km/h";
        } else {
          statSpd.textContent = "—";
        }
      }

      // Render map route
      const activeWaypoints = isRiding ? waypoints : lastWaypoints;

      if (this._config.snap_to_roads && activeWaypoints.length >= 2) {
        this._rendering = true;
        snapToRoads(activeWaypoints)
          .then((snapped) => {
            this._renderRoute(snapped, isRiding);
          })
          .catch(() => {
            this._renderRoute(activeWaypoints, isRiding);
          })
          .finally(() => {
            this._rendering = false;
          });
      } else {
        this._renderRoute(activeWaypoints, isRiding);
      }
    }

    _renderRoute(waypoints, isRiding) {
      const L = window.L;
      const map = this._map;
      if (!L || !map) return;

      // Clear previous layers
      this._layers.forEach((l) => map.removeLayer(l));
      this._layers = [];

      const weight = isRiding ? 5 : 3;

      if (!waypoints || waypoints.length === 0) {
        // Try centering on device tracker
        const tracker = this._resolveTracker();
        if (tracker && tracker.attributes) {
          const lat = tracker.attributes.latitude;
          const lon = tracker.attributes.longitude;
          if (lat != null && lon != null) {
            map.setView([lat, lon], 15);
          }
        }
        // Show no-data in map area – we rely on the empty map tile
        return;
      }

      const bounds = L.latLngBounds();

      // Draw one polyline per consecutive segment pair, coloured by speed
      for (let i = 0; i < waypoints.length - 1; i++) {
        const wp0 = waypoints[i];
        const wp1 = waypoints[i + 1];
        const spd = (wp0[2] + wp1[2]) / 2;
        const color = speedColor(spd);

        const segment = L.polyline(
          [
            [wp0[0], wp0[1]],
            [wp1[0], wp1[1]],
          ],
          {
            color,
            weight,
            smoothFactor: 1.5,
            opacity: 0.9,
          }
        );

        // Tooltip on hover
        segment.bindTooltip(`${Math.round(spd)} km/h`, {
          sticky: true,
          direction: "top",
          offset: [0, -4],
          className: "ktm-speed-tooltip",
        });

        segment.addTo(map);
        this._layers.push(segment);
        bounds.extend([wp0[0], wp0[1]]);
        bounds.extend([wp1[0], wp1[1]]);
      }

      // Start dot (green)
      if (waypoints.length >= 1) {
        const start = waypoints[0];
        const startDot = L.circleMarker([start[0], start[1]], {
          radius: 7,
          color: "#fff",
          weight: 2,
          fillColor: "#4CAF50",
          fillOpacity: 1,
        }).bindTooltip("Start", { direction: "top" });
        startDot.addTo(map);
        this._layers.push(startDot);
      }

      // Current / end dot
      const last = waypoints[waypoints.length - 1];
      const endColor = isRiding ? "#FF6600" : "#888";
      const endLabel = isRiding ? "🏍 Riding" : "🏍 Parked";
      const endRadius = isRiding ? 10 : 8;

      const endDot = L.circleMarker([last[0], last[1]], {
        radius: endRadius,
        color: "#fff",
        weight: 2,
        fillColor: endColor,
        fillOpacity: 1,
      }).bindTooltip(endLabel, { direction: "top", permanent: false });
      endDot.addTo(map);
      this._layers.push(endDot);

      // Fit bounds if we have a real route
      if (waypoints.length >= 2) {
        try {
          map.fitBounds(bounds, { padding: [30, 30] });
        } catch (_) {}
      } else if (waypoints.length === 1) {
        map.setView([last[0], last[1]], 15);
      }
    }
  }

  // -----------------------------------------------------------------------
  // Register
  // -----------------------------------------------------------------------
  if (!customElements.get("ktm-route-card")) {
    customElements.define("ktm-route-card", KtmRouteCard);
  }
})();
