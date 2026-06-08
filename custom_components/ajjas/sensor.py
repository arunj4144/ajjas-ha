from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfSpeed, UnitOfLength, UnitOfElectricPotential
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import AjjasCoordinator

SENSORS = [
    {
        "key": "speed",
        "name": "Speed",
        "icon": "mdi:speedometer",
        "unit": UnitOfSpeed.KILOMETERS_PER_HOUR,
        "device_class": SensorDeviceClass.SPEED,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    {
        "key": "battery_voltage",
        "name": "Battery Voltage",
        "icon": "mdi:car-battery",
        "unit": UnitOfElectricPotential.VOLT,
        "device_class": SensorDeviceClass.VOLTAGE,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    {
        "key": "voltage_level",
        "name": "Battery Level",
        "icon": "mdi:battery",
        "unit": None,
        "device_class": None,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    {
        "key": "odometer",
        "name": "Odometer",
        "icon": "mdi:counter",
        "unit": UnitOfLength.KILOMETERS,
        "device_class": SensorDeviceClass.DISTANCE,
        "state_class": SensorStateClass.TOTAL_INCREASING,
    },
    {
        "key": "today_distance",
        "name": "Today's Distance",
        "icon": "mdi:map-marker-distance",
        "unit": UnitOfLength.KILOMETERS,
        "device_class": SensorDeviceClass.DISTANCE,
        "state_class": SensorStateClass.TOTAL_INCREASING,
    },
    {
        "key": "yesterday_distance",
        "name": "Yesterday's Distance",
        "icon": "mdi:map-marker-distance",
        "unit": UnitOfLength.KILOMETERS,
        "device_class": SensorDeviceClass.DISTANCE,
        "state_class": SensorStateClass.MEASUREMENT,
    },
    {
        "key": "bearing",
        "name": "Bearing",
        "icon": "mdi:compass",
        "unit": "°",
        "device_class": None,
        "state_class": SensorStateClass.MEASUREMENT,
    },
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: AjjasCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([AjjasSensor(coordinator, entry, s) for s in SENSORS])


class AjjasSensor(CoordinatorEntity, SensorEntity):
    def __init__(self, coordinator: AjjasCoordinator, entry: ConfigEntry, config: dict) -> None:
        super().__init__(coordinator)
        self._key = config["key"]
        self._attr_name = f"Ajjas {config['name']}"
        self._attr_unique_id = f"{entry.entry_id}_{self._key}"
        self._attr_icon = config["icon"]
        self._attr_native_unit_of_measurement = config["unit"]
        self._attr_device_class = config["device_class"]
        self._attr_state_class = config["state_class"]
        self._attr_device_info = {
            "identifiers": {(DOMAIN, str(coordinator.vehicle_id))},
            "name": "Ajjas Vehicle",
            "manufacturer": "Ajjas",
            "model": "GPS Tracker",
        }

    @property
    def native_value(self):
        return self.coordinator.data.get(self._key)
