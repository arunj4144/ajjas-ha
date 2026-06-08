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
        "name": "Today Distance",
        "icon": "mdi:map-marker-distance",
        "unit": UnitOfLength.KILOMETERS,
        "device_class": SensorDeviceClass.DISTANCE,
        "state_class": SensorStateClass.TOTAL_INCREASING,
    },
    {
        "key": "yesterday_distance",
        "name": "Yesterday Distance",
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
    entities: list = [AjjasSensor(coordinator, entry, s) for s in SENSORS]
    entities.append(AjjasRidesSensor(coordinator, entry))
    entities.append(AjjasOverspeedSensor(coordinator, entry))
    entities.append(AjjasGeofenceSensor(coordinator, entry))
    async_add_entities(entities)


def _device_info(coordinator: AjjasCoordinator) -> dict:
    return {
        "identifiers": {(DOMAIN, str(coordinator.vehicle_id))},
        "name": "Ajjas Vehicle",
        "manufacturer": "Ajjas",
        "model": "GPS Tracker",
    }


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
        self._attr_device_info = _device_info(coordinator)

    @property
    def native_value(self):
        return self.coordinator.data.get(self._key)


class AjjasRidesSensor(CoordinatorEntity, SensorEntity):
    """Shows count of past rides with last ride details as attributes."""

    def __init__(self, coordinator: AjjasCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_name = "Ajjas Past Rides"
        self._attr_unique_id = f"{entry.entry_id}_past_rides"
        self._attr_icon = "mdi:motorbike"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_device_info = _device_info(coordinator)

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.get("rides", []))

    @property
    def extra_state_attributes(self) -> dict:
        rides = self.coordinator.data.get("rides", [])
        if not rides:
            return {}
        last = rides[-1]
        return {
            "last_ride_start": last.get("fromTs"),
            "last_ride_end": last.get("toTs"),
            "last_ride_distance_km": round(last.get("dst", 0) / 1000, 2),
            "last_ride_avg_speed": round(last.get("avs", 0), 1),
            "last_ride_duration_min": round(last.get("dur", 0) / 60, 1),
            "last_ride_start_lat": last.get("flat"),
            "last_ride_start_lng": last.get("flng"),
            "rides": [
                {
                    "start": r.get("fromTs"),
                    "end": r.get("toTs"),
                    "distance_km": round(r.get("dst", 0) / 1000, 2),
                    "avg_speed": round(r.get("avs", 0), 1),
                    "duration_min": round(r.get("dur", 0) / 60, 1),
                }
                for r in rides[-10:]
            ],
        }


class AjjasOverspeedSensor(CoordinatorEntity, SensorEntity):
    """Shows count of overspeed zones."""

    def __init__(self, coordinator: AjjasCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_name = "Ajjas Overspeed Zones"
        self._attr_unique_id = f"{entry.entry_id}_overspeed_zones"
        self._attr_icon = "mdi:speedometer-slow"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_device_info = _device_info(coordinator)

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.get("overspeed_zones", []))

    @property
    def extra_state_attributes(self) -> dict:
        return {"zones": self.coordinator.data.get("overspeed_zones", [])}


class AjjasGeofenceSensor(CoordinatorEntity, SensorEntity):
    """Shows count of geofences."""

    def __init__(self, coordinator: AjjasCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_name = "Ajjas Geofences"
        self._attr_unique_id = f"{entry.entry_id}_geofences"
        self._attr_icon = "mdi:map-marker-radius"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_device_info = _device_info(coordinator)

    @property
    def native_value(self) -> int:
        return len(self.coordinator.data.get("geofences", []))

    @property
    def extra_state_attributes(self) -> dict:
        return {"geofences": self.coordinator.data.get("geofences", [])}
