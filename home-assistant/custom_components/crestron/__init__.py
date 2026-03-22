"""Crestron integration for Home Assistant.

Connects to a Crestron processor via the CIP protocol over WebSocket
using the pycrestron library. Provides entity platforms for lights,
switches, media players, and sensors.
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant

from pycrestron import CrestronHub

from .const import CONF_IP_ID, DOMAIN, PLATFORMS

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Crestron from a config entry."""
    hub = CrestronHub(
        host=entry.data[CONF_HOST],
        ip_id=entry.data[CONF_IP_ID],
        port=entry.data.get(CONF_PORT, 49200),
        username=entry.data.get(CONF_USERNAME),
        password=entry.data.get(CONF_PASSWORD),
    )

    try:
        await hub.start()
    except Exception as exc:
        _LOGGER.error("Failed to connect to Crestron processor: %s", exc)
        return False

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = hub

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    hub: CrestronHub = hass.data[DOMAIN][entry.entry_id]
    await hub.stop()

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
