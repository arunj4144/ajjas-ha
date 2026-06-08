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
        data = self.coordinator.data
        return {
            "bearing": data.get("bearing"),
            "speed": data.get("speed"),
            "ignition": data.get("ignition"),
            "last_seen": data.get("last_seen"),
            "battery_voltage": data.get("battery_voltage"),
        }
