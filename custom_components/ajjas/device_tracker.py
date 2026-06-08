from homeassistant.components.device_tracker import TrackerEntity, SourceType
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AjjasCoordinator


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: AjjasCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AjjasDeviceTracker(coordinator, entry)])


class AjjasDeviceTracker(CoordinatorEntity, TrackerEntity):
    def __init__(self, coordinator: AjjasCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_name = "Ajjas Vehicle Location"
        self._attr_unique_id = f"{entry.entry_id}_tracker"
        self._attr_icon = "mdi:motorbike"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, str(coordinator.vehicle_id))},
            "name": "Ajjas Vehicle",
            "manufacturer": "Ajjas",
            "model": "GPS Tracker",
        }

    @property
    def source_type(self) -> SourceType:
        return SourceType.GPS

    @property
    def latitude(self) -> float | None:
        return self.coordinator.data.get("latitude")

    @property
    def longitude(self) -> float | None:
        return self.coordinator.data.get("longitude")

    @property
    def extra_state_attributes(self) -> dict:
        d = self.coordinator.data
        return {
            "bearing": d.get("bearing"),
            "speed": d.get("speed"),
            "ignition": d.get("ignition"),
            "last_seen": d.get("last_seen"),
            "battery_voltage": d.get("battery_voltage"),
            "registration": d.get("registration"),
            "make": d.get("make"),
            "model": d.get("model"),
            "tank_capacity_l": d.get("tank_capacity"),
            "mileage_kmpl": d.get("mileage"),
            "relay_enabled": d.get("relay_enabled"),
        }
