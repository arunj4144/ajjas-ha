"""Sensor platform for Ajjas – KTM 390 Adventure themed."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    UnitOfElectricPotential,
    UnitOfLength,
    UnitOfSpeed,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AjjasCoordinator

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Device info helper
# ---------------------------------------------------------------------------

def _device_info(coordinator: AjjasCoordinator) -> dict:
    d = coordinator.data or {}
    return {
        "identifiers": {(DOMAIN, str(coordinator.vehicle_id))},
        "name": "KTM 390 ADV",
        "manufacturer": d.get("make") or "KTM",
        "model": d.get("model") or "390 Adventure",
        "serial_number": d.get("imei"),
    }


# ---------------------------------------------------------------------------
# Sensor descriptions
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True)
class AjjasSensorDescription(SensorEntityDescription):
    """Extended sensor description carrying optional extra kwargs."""


SENSORS: list[AjjasSensorDescription] = [
    AjjasSensorDescription(
        key="speed",
        name="KTM 390 ADV Speed",
        icon="mdi:speedometer",
        native_unit_of_measurement=UnitOfSpeed.KILOMETERS_PER_HOUR,
        device_class=SensorDeviceClass.SPEED,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AjjasSensorDescription(
        key="battery_voltage",
        name="KTM 390 ADV Vehicle Battery",
        icon="mdi:car-battery",
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AjjasSensorDescription(
        key="voltage_level",
        name="KTM 390 ADV GPS Tracker Battery Level",
        icon="mdi:battery-bluetooth",
        native_unit_of_measurement=None,
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AjjasSensorDescription(
        key="odometer",
        name="KTM 390 ADV Odometer",
        icon="mdi:counter",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    AjjasSensorDescription(
        key="today_distance",
        name="KTM 390 ADV Today's Ride",
        icon="mdi:map-marker-distance",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.TOTAL_INCREASING,
    ),
    AjjasSensorDescription(
        key="yesterday_distance",
        name="KTM 390 ADV Yesterday's Ride",
        icon="mdi:map-marker-distance",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AjjasSensorDescription(
        key="bearing",
        name="KTM 390 ADV Heading",
        icon="mdi:compass-rose",
        native_unit_of_measurement="°",
        device_class=None,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AjjasSensorDescription(
        key="ride_distance_km",
        name="KTM 390 ADV Current Ride",
        icon="mdi:map-marker-path",
        native_unit_of_measurement=UnitOfLength.KILOMETERS,
        device_class=SensorDeviceClass.DISTANCE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
]


# ---------------------------------------------------------------------------
# Platform setup
# ---------------------------------------------------------------------------

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AjjasCoordinator = hass.data[DOMAIN][entry.entry_id]

    entities: list[SensorEntity] = []

    for description in SENSORS:
        entities.append(AjjasSensor(coordinator, entry, description))

    entities.append(KtmRideTrackSensor(coordinator, entry))
    entities.append(KtmTripLogSensor(coordinator, entry))
    entities.append(KtmSpeedZonesSensor(coordinator, entry))
    entities.append(KtmGeofenceSensor(coordinator, entry))

    async_add_entities(entities)


# ---------------------------------------------------------------------------
# Generic sensor
# ---------------------------------------------------------------------------

class AjjasSensor(CoordinatorEntity[AjjasCoordinator], SensorEntity):
    """A sensor that reads a single key from coordinator data."""

    entity_description: AjjasSensorDescription

    def __init__(
        self,
        coordinator: AjjasCoordinator,
        entry: ConfigEntry,
        description: AjjasSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = _device_info(coordinator)

    @property
    def native_value(self) -> Any:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self.entity_description.key)


# ---------------------------------------------------------------------------
# KtmRideTrackSensor
# ---------------------------------------------------------------------------

class KtmRideTrackSensor(CoordinatorEntity[AjjasCoordinator], SensorEntity):
    """Live ride track – exposes waypoints and ride metadata as attributes."""

    _attr_name = "KTM 390 ADV Ride Track"
    _attr_icon = "mdi:map-marker-path"
    _attr_has_entity_name = False

    def __init__(self, coordinator: AjjasCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_ride_track"
        self._attr_device_info = _device_info(coordinator)

    @property
    def native_value(self) -> str:
        if self.coordinator.data and self.coordinator.data.get("is_riding"):
            return "riding"
        return "parked"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.coordinator.data or {}
        waypoints: list = d.get("ride_waypoints") or []
        last_waypoints: list = d.get("last_ride_waypoints") or []
        return {
            "waypoints": waypoints[-200:],
            "waypoint_count": len(waypoints),
            "ride_distance_km": d.get("ride_distance_km", 0),
            "is_riding": d.get("is_riding", False),
            "ride_start_ts": d.get("ride_start_ts"),
            "last_ride_waypoints": last_waypoints[-200:],
            "trip_history": self.coordinator.trip_history,
        }


# ---------------------------------------------------------------------------
# KtmTripLogSensor  (was AjjasRidesSensor)
# ---------------------------------------------------------------------------

class KtmTripLogSensor(CoordinatorEntity[AjjasCoordinator], SensorEntity):
    """Summarises recent trips from coordinator ride data."""

    _attr_name = "KTM 390 ADV Trip Log"
    _attr_icon = "mdi:motorbike"
    _attr_has_entity_name = False

    def __init__(self, coordinator: AjjasCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_trip_log"
        self._attr_device_info = _device_info(coordinator)

    @property
    def native_value(self) -> int:
        rides = (self.coordinator.data or {}).get("rides") or []
        return len(rides)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        rides: list[dict] = (self.coordinator.data or {}).get("rides") or []
        if not rides:
            return {"recent_trips": []}

        def _parse(r: dict) -> dict:
            dist = r.get("distance") or r.get("dist") or r.get("distance_km") or 0
            avg_spd = r.get("avgSpeed") or r.get("avg_speed") or r.get("avg_speed_kmh") or 0
            dur = r.get("duration") or r.get("duration_min") or 0
            return {
                "start": r.get("startTime") or r.get("start"),
                "end": r.get("endTime") or r.get("end"),
                "distance_km": round(float(dist), 2),
                "avg_speed_kmh": round(float(avg_spd), 1),
                "duration_min": round(float(dur), 1),
            }

        recent = [_parse(r) for r in rides[-10:]]
        last = recent[-1] if recent else {}
        return {
            "last_trip_start": last.get("start"),
            "last_trip_end": last.get("end"),
            "last_trip_distance_km": last.get("distance_km"),
            "last_trip_avg_speed_kmh": last.get("avg_speed_kmh"),
            "last_trip_duration_min": last.get("duration_min"),
            "recent_trips": recent,
        }


# ---------------------------------------------------------------------------
# KtmSpeedZonesSensor  (was AjjasOverspeedSensor)
# ---------------------------------------------------------------------------

class KtmSpeedZonesSensor(CoordinatorEntity[AjjasCoordinator], SensorEntity):
    """Reports speed zone / overspeed events."""

    _attr_name = "KTM 390 ADV Speed Zones"
    _attr_icon = "mdi:speedometer-slow"
    _attr_has_entity_name = False

    def __init__(self, coordinator: AjjasCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_speed_zones"
        self._attr_device_info = _device_info(coordinator)

    @property
    def native_value(self) -> int:
        events = (self.coordinator.data or {}).get("speed_zone_events") or []
        return len(events)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "speed_zone_events": (self.coordinator.data or {}).get("speed_zone_events") or [],
        }


# ---------------------------------------------------------------------------
# KtmGeofenceSensor
# ---------------------------------------------------------------------------

class KtmGeofenceSensor(CoordinatorEntity[AjjasCoordinator], SensorEntity):
    """Reports geofence events."""

    _attr_name = "KTM 390 ADV Geofences"
    _attr_icon = "mdi:map-marker-radius"
    _attr_has_entity_name = False

    def __init__(self, coordinator: AjjasCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_geofences"
        self._attr_device_info = _device_info(coordinator)

    @property
    def native_value(self) -> int:
        geofences = (self.coordinator.data or {}).get("geofences") or []
        return len(geofences)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "geofences": (self.coordinator.data or {}).get("geofences") or [],
            "geofence_events": (self.coordinator.data or {}).get("geofence_events") or [],
        }
