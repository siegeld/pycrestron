"""Crestron media player platform.

Each media player maps to:
  - Digital join: power on/off (feedback + command)
  - Digital join: mute (feedback + command)
  - Analog join: volume 0-65535 (feedback + command)
  - Serial join: source name (feedback only)
"""
from __future__ import annotations

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from pycrestron import CrestronHub

from .const import DOMAIN

# ---------------------------------------------------------------
# CUSTOMIZE THIS: Define your media players and their join numbers.
# ---------------------------------------------------------------
MEDIA_PLAYERS = [
    {
        "name": "Living Room Audio",
        "power_join": 5,
        "mute_join": 6,
        "volume_join": 5,
        "source_join": 1,
    },
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Crestron media players."""
    hub: CrestronHub = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            CrestronMediaPlayer(
                hub,
                cfg["name"],
                cfg["power_join"],
                cfg["mute_join"],
                cfg["volume_join"],
                cfg["source_join"],
            )
            for cfg in MEDIA_PLAYERS
        ]
    )


class CrestronMediaPlayer(MediaPlayerEntity):
    """Media player controlled via Crestron joins."""

    _attr_supported_features = (
        MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_MUTE
        | MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
    )

    def __init__(
        self,
        hub: CrestronHub,
        name: str,
        power_join: int,
        mute_join: int,
        volume_join: int,
        source_join: int,
    ) -> None:
        self._hub = hub
        self._attr_name = name
        self._attr_unique_id = f"crestron_media_{power_join}"
        self._power_join = power_join
        self._mute_join = mute_join
        self._volume_join = volume_join
        self._source_join = source_join
        self._is_on = False
        self._is_muted = False
        self._volume = 0.0
        self._source = ""

    async def async_added_to_hass(self) -> None:
        self._hub.register_digital(self._power_join, self._power_cb)
        self._hub.register_digital(self._mute_join, self._mute_cb)
        self._hub.register_analog(self._volume_join, self._volume_cb)
        self._hub.register_serial(self._source_join, self._source_cb)
        self._hub.on_availability(self._avail_cb)

    @callback
    def _power_cb(self, value: bool) -> None:
        self._is_on = value
        self.async_write_ha_state()

    @callback
    def _mute_cb(self, value: bool) -> None:
        self._is_muted = value
        self.async_write_ha_state()

    @callback
    def _volume_cb(self, value: int) -> None:
        self._volume = value / 65535
        self.async_write_ha_state()

    @callback
    def _source_cb(self, value: str) -> None:
        self._source = value
        self.async_write_ha_state()

    @callback
    def _avail_cb(self, available: bool) -> None:
        self._attr_available = available
        self.async_write_ha_state()

    @property
    def state(self) -> MediaPlayerState:
        return MediaPlayerState.ON if self._is_on else MediaPlayerState.OFF

    @property
    def volume_level(self) -> float:
        return self._volume

    @property
    def is_volume_muted(self) -> bool:
        return self._is_muted

    @property
    def source(self) -> str:
        return self._source

    async def async_turn_on(self) -> None:
        await self._hub.set_digital(self._power_join, True)

    async def async_turn_off(self) -> None:
        await self._hub.set_digital(self._power_join, False)

    async def async_set_volume_level(self, volume: float) -> None:
        await self._hub.set_analog(self._volume_join, int(volume * 65535))

    async def async_mute_volume(self, mute: bool) -> None:
        await self._hub.set_digital(self._mute_join, mute)
