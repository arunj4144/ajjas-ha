from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorDeviceClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AjjasCoordinator

BINARY_SENSORS = [
    {
        "key": "ignition",
        "name": "Ignition",
        "icon_on": "mdi:key-variant",
        "icon_off": "mdi:key-off",
        "device_class": BinarySensorDeviceClass.POWER,
    },
    {
        "key": "main_power",
        "name": "Main Power",
        "icon_on": "mdi:power-plug",
        "icon_off": "mdi:power-plug-off",
        "device_class": BinarySensorDeviceClass.PLUG,
    },
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: AjjasCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AjjasBinarySensor(coordinator, entry, s) for s in BINARY_SENSORS])


class AjjasBinarySensor(CoordinatorEntity, BinarySensorEntity):
    def __init__(self, coordinator: AjjasCoordinator, entry: ConfigEntry, config: dict) -> None:
        super().__init__(coordinator)
        self._key = config["key"]
        self._icon_on = config["icon_on"]
        self._icon_off = config["icon_off"]
        self._attr_name = f"Ajjas {config['name']}"
        self._attr_unique_id = f"{entry.entry_id}_{self._key}"
        self._attr_device_class = config["device_class"]
        self._attr_device_info = {
            "identifiers": {(DOMAIN, str(coordinator.vehicle_id))},
            "name": "Ajjas Vehicle",
            "manufacturer": "Ajjas",
            "model": "GPS Tracker",
        }

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data.get(self._key)

    @property
    def icon(self) -> str:
        return self._icon_on if self.is_on else self._icon_off
