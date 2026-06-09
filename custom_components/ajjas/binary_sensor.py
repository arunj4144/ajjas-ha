"""Binary sensor platform for Ajjas – KTM 390 Adventure themed."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AjjasCoordinator

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Device info helper (matches sensor.py)
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
# Sensor description
# ---------------------------------------------------------------------------

@dataclass(frozen=True, kw_only=True)
class AjjasBinarySensorDescription(BinarySensorEntityDescription):
    icon_on: str = "mdi:checkbox-marked-circle"
    icon_off: str = "mdi:checkbox-blank-circle-outline"


BINARY_SENSORS: list[AjjasBinarySensorDescription] = [
    AjjasBinarySensorDescription(
        key="ignition",
        name="KTM 390 ADV Ignition",
        icon_on="mdi:key-wireless",
        icon_off="mdi:key-off",
        device_class=BinarySensorDeviceClass.RUNNING,
    ),
    AjjasBinarySensorDescription(
        key="main_power",
        name="KTM 390 ADV GPS Tracker Power",
        icon_on="mdi:power-plug",
        icon_off="mdi:power-plug-off",
        device_class=BinarySensorDeviceClass.PLUG,
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
    async_add_entities(
        AjjasBinarySensor(coordinator, entry, description)
        for description in BINARY_SENSORS
    )


# ---------------------------------------------------------------------------
# Entity class
# ---------------------------------------------------------------------------

class AjjasBinarySensor(CoordinatorEntity[AjjasCoordinator], BinarySensorEntity):
    """A binary sensor backed by a single boolean key in coordinator data."""

    entity_description: AjjasBinarySensorDescription

    def __init__(
        self,
        coordinator: AjjasCoordinator,
        entry: ConfigEntry,
        description: AjjasBinarySensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = _device_info(coordinator)

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        raw = self.coordinator.data.get(self.entity_description.key)
        if raw is None:
            return None
        return bool(raw)

    @property
    def icon(self) -> str:
        if self.is_on:
            return self.entity_description.icon_on
        return self.entity_description.icon_off
