"""Crestron switch platform.

Each switch maps to a single digital join (feedback + command).
"""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from pycrestron import CrestronHub

from .const import DOMAIN

# ---------------------------------------------------------------
# CUSTOMIZE THIS: Define your switches and their join numbers.
# ---------------------------------------------------------------
SWITCHES = [
    {"name": "Projector Screen", "join": 10},
    {"name": "Amplifier Power", "join": 11},
    {"name": "Fireplace", "join": 12},
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Crestron switches."""
    hub: CrestronHub = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [CrestronSwitch(hub, cfg["name"], cfg["join"]) for cfg in SWITCHES]
    )


class CrestronSwitch(SwitchEntity):
    """A switch controlled via a Crestron digital join."""

    def __init__(self, hub: CrestronHub, name: str, join: int) -> None:
        self._hub = hub
        self._attr_name = name
        self._attr_unique_id = f"crestron_switch_{join}"
        self._join = join
        self._is_on = False

    async def async_added_to_hass(self) -> None:
        self._hub.register_digital(self._join, self._state_cb)
        self._hub.on_availability(self._avail_cb)

    @callback
    def _state_cb(self, value: bool) -> None:
        self._is_on = value
        self.async_write_ha_state()

    @callback
    def _avail_cb(self, available: bool) -> None:
        self._attr_available = available
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs) -> None:
        await self._hub.set_digital(self._join, True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._hub.set_digital(self._join, False)
