"""Crestron sensor platform.

Supports analog sensors (numeric values) and serial sensors (text).
"""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from pycrestron import CrestronHub

from .const import DOMAIN

# ---------------------------------------------------------------
# CUSTOMIZE THIS: Define your sensors and their join numbers.
# ---------------------------------------------------------------
ANALOG_SENSORS = [
    {"name": "Room Temperature", "join": 10, "unit": "°F", "scale": 10},
    {"name": "Humidity", "join": 11, "unit": "%", "scale": 1},
]

SERIAL_SENSORS = [
    {"name": "Current Source", "join": 1},
    {"name": "Now Playing", "join": 2},
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Crestron sensors."""
    hub: CrestronHub = hass.data[DOMAIN][entry.entry_id]

    entities = []
    for cfg in ANALOG_SENSORS:
        entities.append(
            CrestronAnalogSensor(
                hub, cfg["name"], cfg["join"], cfg.get("unit", ""), cfg.get("scale", 1)
            )
        )
    for cfg in SERIAL_SENSORS:
        entities.append(CrestronSerialSensor(hub, cfg["name"], cfg["join"]))

    async_add_entities(entities)


class CrestronAnalogSensor(SensorEntity):
    """Sensor from a Crestron analog join."""

    def __init__(
        self,
        hub: CrestronHub,
        name: str,
        join: int,
        unit: str = "",
        scale: float = 1.0,
    ) -> None:
        self._hub = hub
        self._attr_name = name
        self._attr_unique_id = f"crestron_analog_sensor_{join}"
        self._attr_native_unit_of_measurement = unit or None
        self._join = join
        self._scale = scale
        self._value: float | None = None

    async def async_added_to_hass(self) -> None:
        self._hub.register_analog(self._join, self._value_cb)
        self._hub.on_availability(self._avail_cb)

    @callback
    def _value_cb(self, value: int) -> None:
        self._value = value / self._scale if self._scale != 1.0 else float(value)
        self.async_write_ha_state()

    @callback
    def _avail_cb(self, available: bool) -> None:
        self._attr_available = available
        self.async_write_ha_state()

    @property
    def native_value(self) -> float | None:
        return self._value


class CrestronSerialSensor(SensorEntity):
    """Sensor from a Crestron serial join."""

    def __init__(self, hub: CrestronHub, name: str, join: int) -> None:
        self._hub = hub
        self._attr_name = name
        self._attr_unique_id = f"crestron_serial_sensor_{join}"
        self._join = join
        self._value: str | None = None

    async def async_added_to_hass(self) -> None:
        self._hub.register_serial(self._join, self._value_cb)
        self._hub.on_availability(self._avail_cb)

    @callback
    def _value_cb(self, value: str) -> None:
        self._value = value
        self.async_write_ha_state()

    @callback
    def _avail_cb(self, available: bool) -> None:
        self._attr_available = available
        self.async_write_ha_state()

    @property
    def native_value(self) -> str | None:
        return self._value
