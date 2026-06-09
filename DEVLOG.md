# Ajjas HA Integration — Development Log

## Overview

Custom Home Assistant integration for the Ajjas GPS tracker on a **KTM 390 Adventure**.
Tracks live location, speed, ride history, and displays a speed-heatmap route card.

- **HA Server**: `172.16.3.200` (Docker), SSH: `mensait@172.16.3.200` / `Mensa@2025`
- **HA config dir**: `/home/mensait/homeassistant/`
- **Integration path**: `/home/mensait/homeassistant/custom_components/ajjas/`
- **GitHub**: `https://github.com/arunj4144/ajjas-ha`
- **Vehicle**: KL78E4144, KTM 390 ADV, Vehicle ID `329187`

---

## Phase 1 — Bug Fixes (June 8 2026)

### Bug 1: Login appeared to fail (DNS broken in Docker)

The Docker container's `/etc/resolv.conf` had unreliable org DNS servers (`102.8.46.5`, `103.8.45.5`) listed first, causing `aiohttp` DNS resolution failures when connecting to `api.ajjas.com`.

**Fixes applied:**
- Edited `/etc/docker/daemon.json` → `{"dns": ["8.8.8.8", "1.1.1.1"]}`
- Created `/home/mensait/homeassistant/resolv.conf` with `8.8.8.8` / `1.1.1.1`
- Updated `homeassistant-docker-compose.yml` to mount it:
  ```yaml
  volumes:
    - /home/mensait/homeassistant/resolv.conf:/etc/resolv.conf:ro
  ```
- Added `aiohttp.ThreadedResolver()` to coordinator to bypass `aiodns`

> **CRITICAL**: Always restart HA using:
> ```bash
> sudo docker-compose -f /home/mensait/homeassistant-docker-compose.yml up -d --force-recreate
> ```
> `docker restart` does NOT apply compose changes (volume mounts won't update).

### Bug 2: No vehicle data (WS messages sent before server handshake)

The coordinator was sending all WebSocket requests before the server sent `msync`. The Ajjas server silently ignores any messages sent before it sends `msync`.

**Fix**: All WS request sends moved inside the `async for msg in ws:` loop, triggered only after `action == "msync"`.

### Bug 3: vehicle_id always 0

Vehicle ID `329187` is only returned at runtime from the `dynamicData` response — it is not known at setup time.

**Fix**: Coordinator discovers vehicle_id from the first `dynamicData` response.

### Ajjas WebSocket Protocol (important)

| Wrong assumption | Correct |
|---|---|
| Action key is `"type"` | Action key is `"a"` |
| Send `{"type": "getDynamicData"}` | Send `{"a": "getDynamicData"}` |
| Server sends data immediately | Server sends `ready → ver_upd → msync` first; only send after `msync` |
| `locUpd` longitude key is `"lon"` | Server sends `"lng"`; store internally as `"lon"` |

---

## Phase 2 — KTM 390 ADV Revamp (June 9 2026)

### New Features

1. **KTM 390 ADV theming** — all entity names, device name, icons
2. **Live waypoint tracking** — 100m minimum distance between stored points; haversine accumulation
3. **Streaming WS mode** — when ignition ON, suspends 30s polling and opens a persistent WS that pushes `locUpd` in real-time; restores polling when ignition OFF
4. **Trip history** — every completed ride saved (up to 20 trips); downsampled to 50 waypoints per trip for HA attribute storage
5. **Speed heatmap Lovelace card** (`ktm-route-card.js`) — Leaflet.js, trip selector, speed-colored segments, hover tooltips, motorcycle marker
6. **Fixed ignition icon** — `mdi:key-wireless` / `mdi:key-off`, `device_class=RUNNING`
7. **GPS Tracker Battery** — separate entity from vehicle battery (`voltage_level`)
8. **GPS Tracker Power** — binary sensor (`main_power`) with plug icon

### Entity IDs

| Entity | ID |
|---|---|
| Device tracker | `device_tracker.ajjas_vehicle_location` |
| Speed | `sensor.ajjas_speed` |
| Battery voltage | `sensor.ajjas_battery_voltage` |
| Battery level | `sensor.ajjas_battery_level` |
| Odometer | `sensor.ajjas_odometer` |
| Today's ride | `sensor.ajjas_today_distance` |
| Yesterday's ride | `sensor.ajjas_yesterday_distance` |
| Heading/bearing | `sensor.ajjas_bearing` |
| Ignition | `binary_sensor.ajjas_ignition` |
| GPS power | `binary_sensor.ajjas_main_power` |
| Current ride distance | `sensor.ktm_390_adv_current_ride` |
| Ride track (waypoints) | `sensor.ktm_390_adv_ride_track` |
| Trip log | `sensor.ktm_390_adv_trip_log` |
| Speed zones | `sensor.ktm_390_adv_speed_zones` |
| Geofences | `sensor.ktm_390_adv_geofences` |

Old entities (`sensor.ajjas_past_rides`, `sensor.ajjas_overspeed_zones`) kept old IDs due to matching `unique_id`s — delete them from HA UI if unwanted.

---

## Architecture

### coordinator.py

- `AjjasCoordinator(hass, cookie, vehicle_id)` — `DataUpdateCoordinator`, 30s poll interval
- `_get_session()` — creates `aiohttp.ClientSession` with `ThreadedResolver` + `TCPConnector(family=AF_INET)` to avoid `aiodns` failures
- `_fetch_once()` / `_fetch()` (3-attempt retry) — polling via WS; sends `getDynamicData`, `fetchData`, `subVeh`, and `exapireq` for rides/overspeed/geofences after `msync`
- `_start_stream()` — launches background task for live streaming when ignition on
- `_stream_ws_once()` — persistent WS connection during ride; processes `locUpd` in real-time; calls `async_set_updated_data()` so entities update immediately
- `_add_to_waypoints(lat, lon, spd)` — accumulates distance always; stores waypoint only if ≥100m from previous (WAYPOINT_MIN_DIST_KM = 0.1)
- `_complete_trip()` — saves completed ride to `_trip_history`; downsamples to 50 points; clears ride state
- `_inject_ride_state(d)` — writes current ride state into any result dict
- `trip_history` property — exposes `_trip_history` list

**WS send format (all requests after `msync`):**
```json
{"a": "getDynamicData"}
{"a": "fetchData"}
{"a": "subVeh", "d": {"veh": [329187]}}
{"a": "exapireq", "d": {"req": {"url": "/gl/users/rides/...", "method": "POST", ...}}, "r": 10}
```

**Key data parsing:**
```python
def _parse_live(self, v):
    # v = one vehicle dict from wirelessLastSeen[]
    # v.get("lng") → stored as "lon" (server typo)
    # v.get("spd") → "speed"
    # v.get("ignition") NOT v.get("ign") in dynamicData
    # hbt.get("externalVolt") → battery_voltage
    # hbt.get("voltLvl")      → voltage_level (GPS tracker battery %)
    # hbt.get("mainPower")    → main_power
    # hbt.get("dstInfo", {})  → distances in meters, convert /1000
```

### sensor.py — KtmRideTrackSensor attributes

```python
{
    "waypoints":          [[lat, lon, spd], ...],   # current ride, max 200 pts
    "waypoint_count":     int,
    "ride_distance_km":   float,
    "is_riding":          bool,
    "ride_start_ts":      int | None,
    "last_ride_waypoints":[[lat, lon, spd], ...],   # most recent completed, max 200 pts
    "trip_history":       [                          # up to 20 completed trips
        {
            "id":          int,
            "start_ts":    int,    # Unix timestamp
            "end_ts":      int,
            "waypoints":   [[lat, lon, spd], ...],  # 50 pts max (downsampled)
            "distance_km": float,
            "max_speed":   float,
            "avg_speed":   float,
        }, ...
    ],
    "current_lat":        float,   # live GPS lat (for card use)
    "current_lon":        float,   # live GPS lon
    "current_speed":      float,
    "current_bearing":    float,
}
```

### const.py

```python
SCAN_INTERVAL        = 30     # polling interval in seconds
WAYPOINT_BUFFER_SIZE = 500    # max waypoints kept in memory for current ride
WAYPOINT_MIN_DIST_KM = 0.1    # 100m minimum between stored waypoints
TRIP_HISTORY_MAX     = 20     # max completed trips kept in memory
```

---

## Lovelace — KTM Route Card

### Card registration

`/home/mensait/homeassistant/.storage/lovelace_resources` — entry:
```json
{"id": "ktm_route_card_1780987871", "type": "module", "url": "/local/ktm-route-card.js"}
```

Files served from `/home/mensait/homeassistant/www/`:
```
www/
  ktm-route-card.js
  leaflet/
    leaflet.min.js
    leaflet.min.css
```

### Card config (YAML)

```yaml
type: custom:ktm-route-card
entity: sensor.ktm_390_adv_ride_track
title: KTM 390 ADV Route
default_view: last      # current | last | today
map_height: 420
snap_to_roads: false    # true = OSRM road-snapping (needs internet)
```

### Card features

- **Trip selector toolbar**: Current | Last Ride | Today | History ▾
  - **Current** — live route while ignition on (greyed out when parked)
  - **Last Ride** — most recent completed trip
  - **Today** — all trips from today merged
  - **History ▾** — dropdown grouped by day; tap any trip to view its path
- **Motorcycle marker** — 🏍 blue circle when parked; orange + pulsing when riding
- **Speed heatmap** — polylines colored by speed (green→red); hover tooltip shows km/h
- **Start/end dots** — green circle at start, red at end of historical rides
- **Stats bar** — distance, current speed, waypoint count, max speed
- **Speed legend** — color scale at bottom of card
- **HA card editor** — click pencil icon to configure entity, title, default view, height, snap-to-roads

### Shadow DOM issue (resolved in v4)

Versions v1–v3 used shadow DOM. Leaflet CSS was injected as a `<link>` tag into the shadow root — this is **async** and `_initMap()` ran before the CSS loaded, leaving `.leaflet-pane`, `.leaflet-marker-icon` etc. with no positioning styles (tiles clipped, markers invisible).

**Fix (v4+)**: Removed shadow DOM entirely. Leaflet CSS is injected into `document.head` synchronously before any map initialization. All Leaflet elements get styles immediately.

### Bike marker not showing (resolved)

Versions v4–v5 tried to read `lat`/`lon` from `device_tracker.ajjas_vehicle_location` attributes. This could fail if the entity was in a privacy zone, lagged in state propagation, or the entity search returned null.

**Fix**: `KtmRideTrackSensor` now exposes `current_lat`, `current_lon`, `current_speed`, `current_bearing` directly. The card reads these first, falls back to the device_tracker if unavailable.

---

## Dashboard Storage

File: `/home/mensait/homeassistant/.storage/lovelace.ktm_map`

Dashboard: **KTM MAP** (path: `ktm_map` in HA sidebar)

Cards:
1. `custom:ktm-route-card` — route map with trip selector
2. `glance` — ignition, speed, GPS power, battery V, battery %, ride distance
3. `entities` — odometer, today/yesterday distance, trip log

---

## Infrastructure

### Docker Compose

File: `/home/mensait/homeassistant-docker-compose.yml`

Key settings:
```yaml
network_mode: host          # HA binds directly to host network
environment:
  - TZ=Asia/Kolkata
volumes:
  - /home/mensait/homeassistant:/config
  - /home/mensait/homeassistant/resolv.conf:/etc/resolv.conf:ro  # DNS fix
```

### Firewall (iptables via UFW)

Port 8123 allowed in `ufw-user-input` chain. Persisted in `/etc/ufw/user.rules`. If rule disappears after reboot, re-add:
```bash
sudo iptables -I ufw-user-input -p tcp --dport 8123 -j ACCEPT
```

### HA Restart Commands

```bash
# Full restart with compose (applies all volume mounts):
sudo docker-compose -f /home/mensait/homeassistant-docker-compose.yml up -d --force-recreate

# Quick restart (does NOT re-apply volume mounts):
sudo docker restart homeassistant

# Stop / Start (preserves container, applies nothing new):
sudo docker-compose -f /home/mensait/homeassistant-docker-compose.yml stop
sudo docker-compose -f /home/mensait/homeassistant-docker-compose.yml start
```

### Verify DNS inside container

```bash
docker exec homeassistant cat /etc/resolv.conf
# Should show: nameserver 8.8.8.8 / nameserver 1.1.1.1
```

---

## Troubleshooting

| Symptom | Check | Fix |
|---|---|---|
| `172.16.3.200 refused` | `sudo ss -tlnp \| grep 8123` — is HA listening? | HA still starting (~2 min); or iptables rule missing |
| Integration not loading | `docker logs homeassistant \| grep -i 'ajjas\|ERROR'` | Check const.py imports match coordinator.py imports |
| No data / all sensors unavailable | Check `docker exec homeassistant cat /etc/resolv.conf` | DNS fix: ensure resolv.conf mount is active |
| Map tiles not loading | Browser devtools → Network tab | Leaflet JS/CSS paths: `/local/leaflet/leaflet.min.*` |
| Bike marker missing | Check `sensor.ktm_390_adv_ride_track` attributes for `current_lat` | HA restart needed to pick up sensor.py changes |
| Trip history empty | Normal until first ride completes with ignition ON→OFF | Ride with ignition on, then off; trip auto-saves |
| `docker restart` breaks DNS | `/etc/resolv.conf` reverts to container default | Use `docker-compose up -d --force-recreate` instead |

---

## Git History Summary

| Commit | Description |
|---|---|
| Initial commits | Phase 1 fixes: WS protocol, DNS, retries |
| `b51ebf2` | v2 card fixes |
| `60842b3` | v3 card: Leaflet CSS in shadow root (partial fix) |
| `b866a91` | **v4 card**: drop shadow DOM entirely — tiles and markers now render |
| `94532e2` | **v5 card**: trip selector, HA card editor, trip history backend |
| `c395fdd` | Fix bike marker: `current_lat/lon` exposed in sensor, card reads from entity |
