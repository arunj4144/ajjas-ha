"""Device tracker platform for Ajjas – KTM 390 Adventure."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.device_tracker import SourceType
from homeassistant.components.device_tracker.config_entry import TrackerEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AjjasCoordinator

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Device info helper (matches sensor.py / binary_sensor.py)
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
# Platform setup
# ---------------------------------------------------------------------------

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: AjjasCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AjjasDeviceTracker(coordinator, entry)])


# ---------------------------------------------------------------------------
# Entity class
# ---------------------------------------------------------------------------

class AjjasDeviceTracker(CoordinatorEntity[AjjasCoordinator], TrackerEntity):
    """GPS tracker entity for the KTM 390 Adventure."""

    _attr_name = "KTM 390 ADV"
    _attr_icon = "mdi:motorbike"
    _attr_has_entity_name = False

    def __init__(self, coordinator: AjjasCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_tracker"
        self._attr_device_info = _device_info(coordinator)

    # ------------------------------------------------------------------
    # TrackerEntity required properties
    # ------------------------------------------------------------------

    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        d = self.coordinator.data or {}
        lat = d.get("lat")
        return float(lat) if lat is not None else None

    @property
    def longitude(self) -> float | None:
        d = self.coordinator.data or {}
        lon = d.get("lon")
        return float(lon) if lon is not None else None

    @property
    def battery_level(self) -> int | None:
        d = self.coordinator.data or {}
        level = d.get("voltage_level")
        if level is None:
            return None
        try:
            return int(level)
        except (TypeError, ValueError):
            return None

    # ------------------------------------------------------------------
    # Extra attributes
    # ------------------------------------------------------------------

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.coordinator.data or {}
        return {
            "bearing": d.get("bearing"),
            "speed_kmh": d.get("speed"),
            "ignition": d.get("ignition"),
            "last_seen": d.get("last_seen"),
            "battery_voltage_v": d.get("battery_voltage"),
            "registration": d.get("registration"),
            "make": d.get("make"),
            "model": d.get("model"),
            "is_riding": d.get("is_riding", False),
            "current_ride_km": d.get("ride_distance_km", 0),
            "relay_enabled": d.get("relay_enabled"),
        }
