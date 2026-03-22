# Building a Home Assistant Integration with pycrestron

This guide walks you through building a complete Home Assistant custom integration that connects to a Crestron processor using `pycrestron`. By the end, you'll have lights, switches, media players, sensors, climate, and covers — all controlled via Crestron joins.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [How It Works](#how-it-works)
3. [Project Structure](#project-structure)
4. [Step 1: Define the Integration](#step-1-define-the-integration)
5. [Step 2: Config Flow (UI Setup)](#step-2-config-flow-ui-setup)
6. [Step 3: Hub Setup](#step-3-hub-setup)
7. [Step 4: Entity Platforms](#step-4-entity-platforms)
8. [Step 5: Join Mapping (YAML Config)](#step-5-join-mapping-yaml-config)
9. [Step 6: Installation](#step-6-installation)
10. [Step 7: Testing](#step-7-testing)
11. [Architecture Decisions](#architecture-decisions)
12. [Common Patterns](#common-patterns)
13. [Troubleshooting](#troubleshooting)

---

## Prerequisites

**Crestron Side:**
- Crestron processor (CP4, MC4, CP3, etc.) with firmware supporting WebSocket on port 49200
- An **XPanel** slot defined in the SIMPL/SIMPL# program with an IP ID (e.g., `0x1a`)
- Web credentials (admin account on the processor's web interface)
- The XPanel's joins wired to your AV/lighting/HVAC program logic

**Home Assistant Side:**
- Home Assistant 2024.1+ (Python 3.11+)
- `pycrestron` installed (either via pip or bundled in the integration)
- Basic familiarity with HA custom component structure

**Crestron XPanel Setup:**

In your SIMPL Windows or SIMPL# program:

1. Open **System Configuration** → **IP Table**
2. Add a new **Xpanel** device
3. Set the **IP ID** (e.g., `1A` hex = `26` decimal)
4. Wire the XPanel's digital, analog, and serial joins to your program's signal routing
5. Compile and upload to the processor

The IP ID you choose here is what you'll enter in the HA configuration UI.

---

## How It Works

```
┌──────────────────┐     WebSocket (CIP)     ┌──────────────────┐
│  Home Assistant   │◄──────────────────────►│  Crestron CP4     │
│                   │    port 49200 (wss)     │                   │
│  ┌─────────────┐  │                         │  ┌─────────────┐  │
│  │ CrestronHub │  │  Digital/Analog/Serial  │  │ SIMPL/SIMPL#│  │
│  │  (pycrestron)│◄─┤  join feedback          │  │  Program    │  │
│  │             ├──►│  join commands          │  │             │  │
│  └──────┬──────┘  │                         │  └─────────────┘  │
│         │         │                         │                   │
│  ┌──────┴──────┐  │                         │  XPanel Slot      │
│  │ HA Entities │  │                         │  IP ID: 0x1A      │
│  │ Light       │  │                         │                   │
│  │ Switch      │  │                         │  Joins:           │
│  │ MediaPlayer │  │                         │  D1-D100 (digital)│
│  │ Sensor      │  │                         │  A1-A100 (analog) │
│  │ Climate     │  │                         │  S1-S50 (serial)  │
│  │ Cover       │  │                         │                   │
│  └─────────────┘  │                         └──────────────────┘
└──────────────────┘
```

**Data flow:**
1. HA entity calls `hub.set_digital(join, value)` → pycrestron sends CIP packet → processor receives signal
2. Processor sends signal feedback → pycrestron parses CIP packet → calls registered callback → HA entity updates state

**Key concept: Join Mapping.** Every HA entity maps to one or more Crestron joins. A light might use digital join 1 (on/off) and analog join 1 (brightness). A thermostat might use analog join 5 (current temp), analog join 6 (setpoint), and serial join 3 (mode text). You define this mapping in your integration's configuration.

---

## Project Structure

```
custom_components/crestron/
├── __init__.py          # Integration setup/teardown
├── manifest.json        # HA integration manifest
├── config_flow.py       # UI-based configuration
├── const.py             # Constants and domain
├── strings.json         # UI strings for config flow
├── light.py             # Light entities
├── switch.py            # Switch entities
├── media_player.py      # Media player entities
├── sensor.py            # Sensor entities
├── climate.py           # Climate/HVAC entities
├── cover.py             # Cover/shade entities
└── translations/
    └── en.json          # English translations
```

---

## Step 1: Define the Integration

### `manifest.json`

```json
{
  "domain": "crestron",
  "name": "Crestron",
  "codeowners": [],
  "config_flow": true,
  "dependencies": [],
  "documentation": "https://github.com/your-repo/pycrestron",
  "iot_class": "local_push",
  "requirements": ["pycrestron==0.1.0"],
  "version": "1.0.0"
}
```

Key fields:
- `"iot_class": "local_push"` — the processor pushes state to us via WebSocket (not polled)
- `"config_flow": true` — enables UI-based setup
- `"requirements"` — HA will auto-install pycrestron

### `const.py`

```python
"""Constants for the Crestron integration."""

DOMAIN = "crestron"

CONF_IP_ID = "ip_id"

# Entity platforms to set up
PLATFORMS = ["light", "switch", "media_player", "sensor", "climate", "cover"]
```

---

## Step 2: Config Flow (UI Setup)

### `config_flow.py`

The config flow lets users add a Crestron processor through the HA UI.

```python
"""Config flow for Crestron integration."""
from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME

from .const import CONF_IP_ID, DOMAIN


class CrestronConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Crestron."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            # Validate connection
            try:
                from pycrestron.auth import fetch_auth_token
                await fetch_auth_token(
                    user_input[CONF_HOST],
                    user_input[CONF_USERNAME],
                    user_input[CONF_PASSWORD],
                )
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                # Parse IP ID (accept hex like "0x1a" or decimal like "26")
                ip_id_str = user_input[CONF_IP_ID]
                ip_id = int(ip_id_str, 0)  # auto-detect hex/decimal
                user_input[CONF_IP_ID] = ip_id

                return self.async_create_entry(
                    title=f"Crestron {user_input[CONF_HOST]}",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_HOST): str,
                vol.Required(CONF_IP_ID, default="0x1a"): str,
                vol.Optional(CONF_PORT, default=49200): int,
                vol.Required(CONF_USERNAME, default="admin"): str,
                vol.Required(CONF_PASSWORD): str,
            }),
            errors=errors,
        )
```

### `strings.json`

```json
{
  "config": {
    "step": {
      "user": {
        "title": "Connect to Crestron Processor",
        "data": {
          "host": "Processor IP Address",
          "ip_id": "IP ID (hex, e.g. 0x1a)",
          "port": "WebSocket Port",
          "username": "Username",
          "password": "Password"
        }
      }
    },
    "error": {
      "cannot_connect": "Unable to connect to the processor. Check IP, credentials, and that the program is running."
    }
  }
}
```

### `translations/en.json`

Same content as `strings.json`.

---

## Step 3: Hub Setup

### `__init__.py`

```python
"""Crestron integration for Home Assistant."""
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
```

---

## Step 4: Entity Platforms

### The Entity Pattern

Every Crestron entity follows the same pattern:

1. **Constructor** — store the hub reference and join numbers
2. **`async_added_to_hass`** — register callbacks with the hub for feedback joins
3. **Callbacks** — update internal state and call `self.async_write_ha_state()`
4. **Service methods** — send signals to the processor via `hub.set_digital/analog/serial`

```python
class MyCrestronEntity(HAEntity):
    def __init__(self, hub, name, feedback_join, command_join):
        self._hub = hub
        self._join_fb = feedback_join
        self._join_cmd = command_join
        self._value = None

    async def async_added_to_hass(self):
        # Register for feedback from processor
        self._hub.register_analog(self._join_fb, self._on_feedback)
        self._hub.on_availability(self._on_availability)

    @callback
    def _on_feedback(self, value):
        self._value = value
        self.async_write_ha_state()  # Tell HA our state changed

    @callback
    def _on_availability(self, available):
        self._attr_available = available
        self.async_write_ha_state()

    async def async_do_something(self):
        # Send command to processor
        await self._hub.set_analog(self._join_cmd, 12345)
```

See the `custom_components/crestron/` directory in this repo for complete implementations of:
- **Light** — digital on/off + analog brightness
- **Switch** — digital on/off
- **Media Player** — digital power/mute + analog volume + serial source
- **Sensor** — analog or serial read-only values
- **Climate** — analog temp/setpoint + digital mode buttons + serial mode text
- **Cover** — digital open/close/stop + analog position

---

## Step 5: Join Mapping (YAML Config)

For a real integration, you'll want to define join mappings in YAML so users can customize which joins map to which entities. Here's one approach using `configuration.yaml`:

```yaml
# configuration.yaml
crestron:
  entities:
    - platform: light
      name: "Living Room Lights"
      power_join: 1          # digital
      brightness_join: 1     # analog

    - platform: light
      name: "Kitchen Lights"
      power_join: 2
      brightness_join: 2

    - platform: switch
      name: "Projector Screen"
      join: 10               # digital

    - platform: media_player
      name: "Living Room Audio"
      power_join: 5
      mute_join: 6
      volume_join: 5         # analog
      source_join: 1         # serial

    - platform: sensor
      name: "Room Temperature"
      join: 10               # analog
      unit: "°F"
      scale: 10              # raw value / 10 = degrees

    - platform: climate
      name: "Main Thermostat"
      current_temp_join: 10  # analog (raw / 10)
      setpoint_join: 11      # analog (raw / 10)
      mode_feedback_join: 3  # serial
      mode_heat_join: 20     # digital (press)
      mode_cool_join: 21
      mode_auto_join: 22
      mode_off_join: 23

    - platform: cover
      name: "Window Shades"
      open_join: 30          # digital (press)
      close_join: 31
      stop_join: 32
      position_fb_join: 15   # analog (0-65535)
      position_set_join: 16  # analog
```

The entity platform files then read this config and create entities accordingly. This keeps the Crestron-specific join wiring in one place.

---

## Step 6: Installation

### Manual Installation

1. Copy the `custom_components/crestron/` folder to your HA `config/custom_components/` directory
2. Install pycrestron: `pip install pycrestron` (in the HA venv)
3. Restart Home Assistant
4. Go to **Settings → Devices & Services → Add Integration → Crestron**
5. Enter your processor IP, IP ID, and credentials

### HACS Installation (future)

Once published, users can install via HACS by adding the repository URL.

### Docker / HA OS

For HA OS or Docker installs where you can't pip install directly:
- Add `pycrestron` to the `requirements` in `manifest.json` — HA will install it automatically
- Or bundle the `pycrestron` package directly inside `custom_components/crestron/`

---

## Step 7: Testing

### Verify Connection

1. Enable debug logging:
   ```yaml
   # configuration.yaml
   logger:
     default: info
     logs:
       custom_components.crestron: debug
       pycrestron: debug
   ```

2. Check the HA log for:
   ```
   CIP connected to 10.11.4.155 (handle=0x0042)
   Processor available
   ```

3. On the Crestron processor, check the XPanel slot shows as connected in the web UI

### Verify Feedback

1. Trigger a signal change on the Crestron side (press a button on a touch panel, change a volume)
2. Check the HA entity state updates in real time
3. If not receiving feedback, check:
   - Join numbers match between SIMPL program and HA config
   - The XPanel slot's IP ID matches what you entered in HA

### Verify Commands

1. Toggle a switch or light entity in HA
2. Verify the action happens on the Crestron side
3. Check the HA log for outgoing signal messages

---

## Architecture Decisions

### Why CrestronHub (Layer 3) for HA?

- **Auto-reconnect** — processors reboot, networks hiccup. The hub handles this transparently.
- **Availability tracking** — HA entities need to know when the processor is offline. The hub provides `available` property and callbacks.
- **State caching** — on reconnect, the processor sends a full state dump. The hub caches everything so entities have correct state immediately.
- **Callback pattern** — matches HA's `async_write_ha_state()` push model perfectly.

### Push vs. Poll

pycrestron uses **push** — the processor sends signal changes as they happen over the persistent WebSocket connection. This means:
- No polling interval to configure
- Instant state updates
- Minimal processor load
- `iot_class: "local_push"` in manifest

### Thread Safety

All pycrestron operations are `async` and run on the HA event loop. Callbacks fire on the event loop, so you can safely call `self.async_write_ha_state()` directly — no need for `hass.loop.call_soon_threadsafe()`.

---

## Common Patterns

### Percentage Conversion (Analog)

Crestron analog joins are 0-65535. HA uses 0-100 or 0-255 for various entities:

```python
# Crestron (0-65535) → HA brightness (0-255)
ha_brightness = int(crestron_value / 65535 * 255)

# HA brightness (0-255) → Crestron (0-65535)
crestron_value = int(ha_brightness / 255 * 65535)

# Crestron (0-65535) → percentage (0-100)
pct = crestron_value / 65535 * 100

# Percentage → Crestron
crestron_value = int(pct / 100 * 65535)

# Temperature (Crestron sends raw * 10, e.g., 720 = 72.0°F)
temp = crestron_value / 10
```

### Momentary Press vs. Toggle

Some Crestron joins are **momentary** (press and release) vs. **latching** (toggle on/off):

```python
# Momentary — press a button (e.g., source select, volume up)
await hub.press(join)  # True → 100ms → False

# Latching — set state directly (e.g., power, mute)
await hub.set_digital(join, True)   # turn on
await hub.set_digital(join, False)  # turn off
```

Your SIMPL program determines which behavior each join has. pycrestron supports both.

### Multiple Entities on Same Join

Multiple HA entities can subscribe to the same join — the hub dispatches to all subscribers:

```python
# Both entities update when analog join 1 changes
hub.register_analog(1, light_entity.on_brightness_change)
hub.register_analog(1, dashboard_entity.on_level_change)
```

---

## Troubleshooting

### "Cannot connect" in config flow

- Verify processor IP is reachable from HA host: `ping 10.11.4.155`
- Verify WebSocket port 49200 is open
- Verify credentials work on the processor web UI (`https://processor-ip`)
- Check that a SIMPL program is running on the processor

### Entity shows "unavailable"

- Check HA logs for connection errors
- Verify the XPanel IP ID matches your config
- The processor may be rebooting — pycrestron will auto-reconnect

### Entity not updating

- Verify the join number matches your SIMPL program
- Use the pycrestron protocol sniffer to see what the processor actually sends
- Check that the join is wired to the XPanel in SIMPL

### Slow response / high latency

- pycrestron uses local WebSocket — latency should be <50ms
- If slow, check network between HA and processor
- Avoid running other WebSocket clients (WebXPanel) on the same IP ID — they'll fight

### HA log shows repeated connect/disconnect

- Token might be expiring — verify credentials are correct
- Processor might have too many connections — check XPanel slot limits
- Network instability — check for packet loss between HA and processor
