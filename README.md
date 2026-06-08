# Ajjas GPS Tracker — Home Assistant Integration

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/custom-components/hacs)

A Home Assistant custom integration for [Ajjas GPS Tracker](https://www.ajjas.com) that exposes your vehicle's live data as HA entities.

## Features

| Entity | Type | Description |
|--------|------|-------------|
| `device_tracker.ajjas_vehicle_location` | Device Tracker | Live GPS position on the map |
| `sensor.ajjas_speed` | Sensor | Current speed (km/h) |
| `sensor.ajjas_battery_voltage` | Sensor | Vehicle battery voltage (V) |
| `sensor.ajjas_battery_level` | Sensor | Battery level (0–7 scale) |
| `sensor.ajjas_odometer` | Sensor | Total distance travelled (km) |
| `sensor.ajjas_today_s_distance` | Sensor | Distance travelled today (km) |
| `sensor.ajjas_yesterday_s_distance` | Sensor | Distance travelled yesterday (km) |
| `sensor.ajjas_bearing` | Sensor | Vehicle heading (degrees) |
| `binary_sensor.ajjas_ignition` | Binary Sensor | Ignition on/off |
| `binary_sensor.ajjas_main_power` | Binary Sensor | Main power connected |

## Installation

### Via HACS (Recommended)
1. Open HACS → Integrations → ⋮ → Custom repositories
2. Add `https://github.com/arunj4144/ajjas-ha` as **Integration**
3. Install **Ajjas GPS Tracker**
4. Restart Home Assistant

### Manual
1. Copy `custom_components/ajjas/` to your HA `config/custom_components/` folder
2. Restart Home Assistant

## Setup

1. Go to **Settings → Devices & Services → Add Integration → Ajjas GPS Tracker**
2. Enter your Ajjas **email and password**

### Manual Cookie Setup (fallback)
If login fails, use the **Manual Cookie** option:
- **Session Cookie**: the `connect.sid` cookie value from the Ajjas app (obtainable via mitmproxy)
- **Vehicle ID**: your numeric vehicle ID (visible in the Ajjas app URL or API traffic)

Your vehicle ID is the number in the Ajjas API requests — e.g. `329187`.
