"""Crestron light platform.

Each light maps to:
  - Digital join: on/off (feedback + command)
  - Analog join: brightness 0-65535 (feedback + command)
"""
from __future__ import annotations

from homeassistant.components.light import ColorMode, LightEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from pycrestron import CrestronHub

from .const import DOMAIN

# ---------------------------------------------------------------
# CUSTOMIZE THIS: Define your lights and their join numbers.
# In a real integration, load these from configuration.yaml or
# a config flow options step.
# ---------------------------------------------------------------
LIGHTS = [
    {"name": "Living Room Lights", "power_join": 1, "brightness_join": 1},
    {"name": "Kitchen Lights", "power_join": 2, "brightness_join": 2},
    {"name": "Bedroom Lights", "power_join": 3, "brightness_join": 3},
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Crestron lights."""
    hub: CrestronHub = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            CrestronLight(hub, cfg["name"], cfg["power_join"], cfg["brightness_join"])
            for cfg in LIGHTS
        ]
    )


class CrestronLight(LightEntity):
    """A dimmable light controlled via Crestron digital + analog joins."""

    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    def __init__(
        self,
        hub: CrestronHub,
        name: str,
        power_join: int,
        brightness_join: int,
    ) -> None:
        self._hub = hub
        self._attr_name = name
        self._attr_unique_id = f"crestron_light_{power_join}_{brightness_join}"
        self._power_join = power_join
        self._brightness_join = brightness_join
        self._is_on = False
        self._brightness = 0

    async def async_added_to_hass(self) -> None:
        """Register callbacks when entity is added."""
        self._hub.register_digital(self._power_join, self._power_cb)
        self._hub.register_analog(self._brightness_join, self._brightness_cb)
        self._hub.on_availability(self._avail_cb)

    @callback
    def _power_cb(self, value: bool) -> None:
        self._is_on = value
        self.async_write_ha_state()

    @callback
    def _brightness_cb(self, value: int) -> None:
        # Crestron 0-65535 → HA 0-255
        self._brightness = int(value / 65535 * 255)
        self.async_write_ha_state()

    @callback
    def _avail_cb(self, available: bool) -> None:
        self._attr_available = available
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        return self._is_on

    @property
    def brightness(self) -> int | None:
        return self._brightness if self._is_on else None

    async def async_turn_on(self, **kwargs) -> None:
        if "brightness" in kwargs:
            analog_val = int(kwargs["brightness"] / 255 * 65535)
            await self._hub.set_analog(self._brightness_join, analog_val)
        await self._hub.set_digital(self._power_join, True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._hub.set_digital(self._power_join, False)
