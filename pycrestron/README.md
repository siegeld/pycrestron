# pycrestron

A pure Python library for communicating with Crestron processors via the CIP (Crestron Internet Protocol) binary protocol over WebSocket. Drop-in replacement for the CH5/WebXPanel JavaScript libraries — no wrappers, no dependencies on Crestron SDKs.

Built for **Home Assistant custom integrations** that run 24/7 with robust reconnection and health monitoring.

---

## Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [Architecture](#architecture)
- [Layer 1: CIPConnection (Raw Protocol)](#layer-1-cipconnection)
- [Layer 2: CrestronClient (Signal-Level)](#layer-2-crestronclient)
- [Layer 3: CrestronHub (Home Assistant)](#layer-3-crestronhub)
- [Authentication](#authentication)
- [Signal Types & Joins](#signal-types--joins)
- [Home Assistant Integration Guide](#home-assistant-integration-guide)
- [Reliability & Reconnection](#reliability--reconnection)
- [Protocol Reference](#protocol-reference)
- [API Reference](#api-reference)
- [Troubleshooting](#troubleshooting)

---

## Installation

```bash
pip install pycrestron
```

Or install from source:

```bash
cd pycrestron
pip install -e .
```

### Dependencies

- `websockets>=12.0` — WebSocket transport
- `aiohttp>=3.9` — HTTPS auth token fetch (Home Assistant already ships this)
- Python >= 3.10

---

## Quick Start

### Toggle a digital join

```python
import asyncio
from pycrestron import CrestronClient

async def main():
    async with CrestronClient("10.11.4.155", 0x1a, username="admin", password="pw") as crestron:
        await crestron.press(1)  # momentary press on digital join 1

asyncio.run(main())
```

### Subscribe to feedback

```python
import asyncio
from pycrestron import CrestronClient

async def main():
    client = CrestronClient("10.11.4.155", 0x1a, username="admin", password="pw")

    # Subscribe BEFORE connecting — callbacks fire when state arrives
    client.subscribe_analog(1, lambda val: print(f"Volume: {val / 65535 * 100:.0f}%"))
    client.subscribe_digital(5, lambda val: print(f"Mute: {val}"))
    client.subscribe_serial(1, lambda val: print(f"Source: {val}"))

    await client.start()

    # Keep running
    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        await client.stop()

asyncio.run(main())
```

### Set analog value (e.g., volume)

```python
async with CrestronClient("10.11.4.155", 0x1a, username="admin", password="pw") as c:
    await c.set_analog(1, 32768)         # 50% volume
    await c.set_serial(1, "Input HDMI")  # set source text
    await c.set_digital(10, True)        # turn on
```

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│  Layer 3: CrestronHub (HA-friendly)             │  Callbacks, state cache, availability
├─────────────────────────────────────────────────┤
│  Layer 2: CrestronClient (signal-level)         │  Digital/Analog/Serial subscribe/publish
├─────────────────────────────────────────────────┤
│  Layer 1: CIPConnection (raw protocol)          │  Packets, WebSocket, auth, heartbeat
└─────────────────────────────────────────────────┘
```

Choose the layer that fits your use case:

| Layer | Class | Use Case |
|-------|-------|----------|
| **1** | `CIPConnection` | Protocol debugging, raw packet inspection, custom implementations |
| **2** | `CrestronClient` | Scripts, automation, any Python app needing Crestron signal I/O |
| **3** | `CrestronHub` | Home Assistant integrations with entity-oriented callbacks |

Each higher layer wraps the one below. You can always access lower layers:

```python
hub.client                    # CrestronHub → CrestronClient
hub.client.connection         # CrestronClient → CIPConnection
```

---

## Layer 1: CIPConnection

Full control over CIP packets. For power users, debugging, and protocol exploration.

### Basic Usage

```python
from pycrestron import CIPConnection

async with CIPConnection("10.11.4.155", 0x1a) as conn:
    # Send a digital join
    await conn.send_digital(1, True)

    # Send an analog value
    await conn.send_analog(1, 32768)

    # Send a serial string
    await conn.send_serial(1, "Hello Crestron")
```

### Raw Packet Monitoring

```python
from pycrestron import CIPConnection

async with CIPConnection("10.11.4.155", 0x1a) as conn:
    # See every CIP packet
    unsub = conn.on_packet(lambda ptype, data: print(f"RX: 0x{ptype:02x} {data.hex()}"))

    await asyncio.sleep(30)  # watch traffic for 30 seconds

    unsub()  # stop monitoring
```

### Send Raw CIP Packets

```python
# Send any packet type with custom payload
await conn.send_packet(0x05, custom_payload_bytes)
```

### Constructor

```python
CIPConnection(
    host: str,           # Processor IP or hostname
    ip_id: int,          # IP Table ID (e.g., 0x1a = 26)
    *,
    port: int = 49200,   # WebSocket port
    use_ssl: bool = True, # Use WSS (required for modern firmware)
)
```

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `connected` | `bool` | True when CIP handshake is complete |
| `state` | `ConnectionState` | Current state machine state |
| `handle` | `int` | CIP connection handle (assigned by processor) |

### Events

```python
conn.on_connect = lambda: print("Connected!")
conn.on_disconnect = lambda: print("Disconnected!")
conn.on_error = lambda exc: print(f"Error: {exc}")
```

---

## Layer 2: CrestronClient

Signal-level API with auto-reconnect. The workhorse for most applications.

### Constructor

```python
CrestronClient(
    host: str,                          # Processor IP or hostname
    ip_id: int,                         # IP Table ID
    *,
    port: int = 49200,                  # WebSocket port
    auth_token: str | None = None,      # Pre-fetched JWT (optional)
    username: str | None = None,        # Web UI username (for auto token fetch)
    password: str | None = None,        # Web UI password
    auto_reconnect: bool = True,        # Auto-reconnect on disconnect
    reconnect_interval: float = 5.0,    # Initial reconnect delay (seconds)
    reconnect_max_interval: float = 300.0,  # Max reconnect delay (5 min cap)
)
```

### Subscribing to Feedback

Feedback flows from the Crestron processor to your Python code. Subscribe to joins to receive real-time updates:

```python
# Digital (bool) — button states, on/off, true/false
unsub = client.subscribe_digital(1, lambda value: print(f"Digital 1: {value}"))

# Analog (int, 0-65535) — levels, volumes, positions
unsub = client.subscribe_analog(1, lambda value: print(f"Analog 1: {value}"))

# Serial (str) — text, names, source labels
unsub = client.subscribe_serial(1, lambda value: print(f"Serial 1: {value}"))

# Unsubscribe when done
unsub()
```

Callbacks fire immediately when the processor sends updated state. On initial connection, the processor typically sends a full state dump — your callbacks will fire for every active join.

### Publishing Signals

Send signals from Python to the Crestron processor:

```python
# Digital
await client.set_digital(1, True)    # set join 1 high
await client.set_digital(1, False)   # set join 1 low
await client.press(1)                # momentary: True → 100ms → False

# Analog (0-65535)
await client.set_analog(1, 0)        # 0%
await client.set_analog(1, 32768)    # 50%
await client.set_analog(1, 65535)    # 100%

# Serial (string)
await client.set_serial(1, "HDMI 1")
```

### Querying Last-Known State

The client caches all received signal values:

```python
# Returns None if never received
volume = client.get_analog(1)        # int | None
is_on = client.get_digital(5)       # bool | None
source = client.get_serial(1)       # str | None
```

State persists across reconnections — if the processor drops and reconnects, your cached values remain until new feedback arrives.

### Events

```python
client.on_connect = lambda: print("Connected")
client.on_disconnect = lambda: print("Disconnected")
client.on_availability_changed = lambda avail: print(f"Available: {avail}")
```

### Accessing Layer 1

```python
# Get the raw CIPConnection for low-level operations
raw = client.connection
raw.on_packet(lambda ptype, data: ...)
await raw.send_packet(0x05, custom_bytes)
```

---

## Layer 3: CrestronHub

Thin wrapper designed for Home Assistant integration patterns. Manages entity callbacks, availability tracking, and coordinator-style updates.

### Constructor

```python
CrestronHub(
    host: str,
    ip_id: int,
    *,
    port: int = 49200,
    username: str | None = None,
    password: str | None = None,
    auth_token: str | None = None,
)
```

### Registration Pattern

```python
from pycrestron import CrestronHub

hub = CrestronHub("10.11.4.155", 0x1a, username="admin", password="pw")

# Register callbacks — these map directly to HA entity update patterns
hub.register_analog(1, lambda val: entity.update_volume(val / 65535 * 100))
hub.register_digital(5, lambda val: entity.update_mute(val))
hub.register_serial(1, lambda val: entity.update_source(val))

# Track processor availability for HA entity availability
hub.on_availability(lambda avail: entity.set_available(avail))

await hub.start()  # runs forever, auto-reconnects

# On HA shutdown:
await hub.stop()
```

### Properties

| Property | Type | Description |
|----------|------|-------------|
| `available` | `bool` | Processor connection active (for HA entity `available` property) |
| `client` | `CrestronClient` | Underlying Layer 2 client |

### All Methods

All signal methods delegate directly to the underlying client:

```python
await hub.set_digital(join, value)
await hub.press(join)
await hub.set_analog(join, value)
await hub.set_serial(join, value)
hub.get_digital(join)
hub.get_analog(join)
hub.get_serial(join)
```

---

## Authentication

Crestron processors with web authentication enabled require a JWT token for WebSocket connections.

### Automatic (Recommended)

Pass `username` and `password` — the library handles token fetch and refresh:

```python
client = CrestronClient("10.11.4.155", 0x1a, username="admin", password="password")
await client.start()  # Token auto-fetched, auto-refreshed on reconnect
```

### Manual Token

If you manage tokens yourself:

```python
from pycrestron.auth import fetch_auth_token

token = await fetch_auth_token("10.11.4.155", "admin", "password")
client = CrestronClient("10.11.4.155", 0x1a, auth_token=token)
```

### No Authentication

Some processors (older firmware, local network) don't require auth:

```python
client = CrestronClient("10.11.4.155", 0x1a)
```

### Token Lifecycle

- Tokens expire after ~5 minutes on the processor
- When `username`/`password` are provided, the client automatically re-fetches a fresh token on each reconnect
- The auth endpoint uses self-signed SSL certificates — certificate verification is disabled by default

### Auth Flow Details

The `fetch_auth_token()` function performs a 3-step HTTP login:

1. `GET /userlogin.html` → Extract TRACKID cookie
2. `POST /userlogin.html` → Submit credentials
3. `GET /cws/websocket/getWebSocketToken` → Receive JWT

---

## Signal Types & Joins

### Digital Joins (bool)

Binary on/off signals. Used for:
- Button presses (momentary or toggle)
- On/off states (power, mute, etc.)
- Enable/disable flags

```python
await client.set_digital(1, True)   # Join 1 = on
await client.press(1)               # Momentary press (100ms)
```

### Analog Joins (int: 0-65535)

16-bit unsigned integer values. Used for:
- Volume levels (0-65535 maps to 0-100%)
- Slider positions
- Numeric displays

```python
# Set to 50%
await client.set_analog(1, 32768)

# Common percentage conversion
pct = analog_value / 65535 * 100
analog_value = int(pct / 100 * 65535)
```

### Serial Joins (str)

Unicode text strings. Used for:
- Source names
- Display text
- Status messages

```python
await client.set_serial(1, "Conference Room A")
```

### Join Numbering

Joins are **1-based** in Crestron programming. This library uses the same numbering:

```python
client.subscribe_digital(1, callback)  # Digital join 1
client.subscribe_analog(1, callback)   # Analog join 1 (separate namespace)
client.subscribe_serial(1, callback)   # Serial join 1 (separate namespace)
```

---

## Home Assistant Integration Guide

### Prerequisites

1. **Crestron Processor** (CP4, MC4, etc.) with WebSocket enabled on port 49200
2. **XPanel Slot** defined in the SIMPL/SIMPL# program with an IP ID (e.g., `0x1a`)
3. **Web credentials** (admin account on the processor web interface)

### Setting Up the XPanel in Crestron

In your SIMPL Windows or SIMPL# program:

1. Open your program
2. In the IP Table, add an **XPanel** (or C2I Ethernet Intersection) device
3. Assign an **IP ID** (e.g., `1A` hex = `26` decimal)
4. Connect the XPanel's joins to your program logic
5. Compile and upload to the processor

The IP ID you assign here is what you pass to pycrestron:

```python
hub = CrestronHub("processor-ip", 0x1a)  # Must match the IP Table entry
```

### Minimal HA Custom Component

#### `custom_components/crestron/__init__.py`

```python
"""Crestron integration for Home Assistant."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from pycrestron import CrestronHub

DOMAIN = "crestron"
PLATFORMS = ["light", "media_player", "switch", "sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Crestron from a config entry."""
    hub = CrestronHub(
        host=entry.data["host"],
        ip_id=entry.data["ip_id"],
        username=entry.data.get("username"),
        password=entry.data.get("password"),
    )

    await hub.start()

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

#### `custom_components/crestron/light.py`

```python
"""Crestron light entity."""
from __future__ import annotations

from homeassistant.components.light import LightEntity, ColorMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from pycrestron import CrestronHub
from . import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub: CrestronHub = hass.data[DOMAIN][entry.entry_id]

    # Example: digital join 1 = on/off, analog join 1 = brightness
    async_add_entities([
        CrestronLight(hub, "Living Room", power_join=1, brightness_join=1),
    ])


class CrestronLight(LightEntity):
    """A light controlled via Crestron joins."""

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
        """Register callbacks when entity is added to HA."""
        self._hub.register_digital(self._power_join, self._power_callback)
        self._hub.register_analog(self._brightness_join, self._brightness_callback)
        self._hub.on_availability(self._availability_callback)

    @callback
    def _power_callback(self, value: bool) -> None:
        self._is_on = value
        self.async_write_ha_state()

    @callback
    def _brightness_callback(self, value: int) -> None:
        self._brightness = int(value / 65535 * 255)
        self.async_write_ha_state()

    @callback
    def _availability_callback(self, available: bool) -> None:
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
```

#### `custom_components/crestron/switch.py`

```python
"""Crestron switch entity."""
from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from pycrestron import CrestronHub
from . import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub: CrestronHub = hass.data[DOMAIN][entry.entry_id]

    # Example: digital join 10 = relay on/off
    async_add_entities([
        CrestronSwitch(hub, "Projector Screen", join=10),
    ])


class CrestronSwitch(SwitchEntity):
    """A switch controlled via a Crestron digital join."""

    def __init__(self, hub: CrestronHub, name: str, join: int) -> None:
        self._hub = hub
        self._attr_name = name
        self._attr_unique_id = f"crestron_switch_{join}"
        self._join = join
        self._is_on = False

    async def async_added_to_hass(self) -> None:
        self._hub.register_digital(self._join, self._state_callback)
        self._hub.on_availability(self._avail_callback)

    @callback
    def _state_callback(self, value: bool) -> None:
        self._is_on = value
        self.async_write_ha_state()

    @callback
    def _avail_callback(self, available: bool) -> None:
        self._attr_available = available
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs) -> None:
        await self._hub.set_digital(self._join, True)

    async def async_turn_off(self, **kwargs) -> None:
        await self._hub.set_digital(self._join, False)
```

#### `custom_components/crestron/media_player.py`

```python
"""Crestron media player entity."""
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
from . import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub: CrestronHub = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([
        CrestronMediaPlayer(
            hub,
            name="Living Room Audio",
            power_join=1,
            mute_join=2,
            volume_join=1,
            source_join=1,
        ),
    ])


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
```

#### `custom_components/crestron/sensor.py`

```python
"""Crestron sensor entities."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from pycrestron import CrestronHub
from . import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    hub: CrestronHub = hass.data[DOMAIN][entry.entry_id]

    async_add_entities([
        CrestronAnalogSensor(hub, "Room Temperature", join=5, unit="°F", scale=10),
        CrestronSerialSensor(hub, "Current Source", join=1),
    ])


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
        self._value = value / self._scale if self._scale != 1.0 else value
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
```

---

## Reliability & Reconnection

pycrestron is designed for 24/7 operation:

### Auto-Reconnect

When the connection drops (network issue, processor reboot, etc.), the client automatically reconnects with exponential backoff:

```
Attempt 1: wait 5s
Attempt 2: wait 10s
Attempt 3: wait 20s
Attempt 4: wait 40s
...
Capped at: 300s (5 minutes)
```

Configure via constructor:

```python
client = CrestronClient(
    "10.11.4.155", 0x1a,
    auto_reconnect=True,         # default
    reconnect_interval=5.0,      # initial delay
    reconnect_max_interval=300.0, # max delay
)
```

### Heartbeat Monitoring

- Client sends heartbeat every **10 seconds**
- If no server message received for **29 seconds**, connection is considered dead
- Dead connections trigger automatic cleanup and reconnect

### Token Refresh

- Auth tokens expire after ~5 minutes on the processor
- When `username`/`password` are provided, a fresh token is fetched on every reconnect attempt
- No need to manage token lifecycle manually

### State Cache

- All signal values are cached locally
- Cache persists across reconnections
- On reconnect, processor sends a full state dump → cache updates automatically
- Query cached values anytime with `get_digital()`, `get_analog()`, `get_serial()`

### Availability Tracking

```python
client.on_availability_changed = lambda avail: print(f"Online: {avail}")
# or
hub.on_availability(lambda avail: entity.set_available(avail))
```

---

## Protocol Reference

### CIP Packet Format

Every CIP packet has this structure:

```
[1 byte]  Packet Type
[2 bytes] Payload Length (big-endian)
[N bytes] Payload
```

### Packet Types

| Code | Name | Direction |
|------|------|-----------|
| `0x01` | CONNECT | C→S |
| `0x02` | CONNECT_RESPONSE | S→C |
| `0x03` | DISCONNECT | Both |
| `0x04` | DISCONNECT_RESPONSE | S→C |
| `0x05` | DATA | Both |
| `0x0B` | AUTHENTICATE | C→S |
| `0x0C` | AUTHENTICATE_RESPONSE | S→C |
| `0x0D` | HEARTBEAT | Both |
| `0x0E` | HEARTBEAT_RESPONSE | Both |
| `0x0F` | PROGRAM_READY | S→C |
| `0x12` | EXTENDED_DATA | Both |
| `0x26` | DEVICE_ROUTER_CONNECT | C→S |
| `0x27` | DEVICE_ROUTER_CONNECT_RESPONSE | S→C |

### Connection Handshake

```
Client                          Processor
  │                                │
  │──── WebSocket Connect ────────→│
  │                                │
  │←─── PROGRAM_READY (0x0F) ─────│  status=2 means ready
  │                                │
  │──── DEVICE_ROUTER_CONNECT ────→│  includes IP ID + auth token
  │     (0x26)                     │
  │                                │
  │←─── CONNECT_RESPONSE (0x27) ──│  returns handle
  │                                │
  │←─── DATA (state dump) ────────│  initial signal values
  │                                │
  │──── HEARTBEAT (0x0D) ─────────→│  every 10s
  │←─── HEARTBEAT_RESPONSE (0x0E)─│
  │                                │
```

### CRESNET Signal Encoding (inside DATA packets)

DATA packets contain one or more CRESNET sub-packets:

```
[1 byte]  CRESNET length (bytes following, including type)
[1 byte]  CRESNET type
[N bytes] Signal data
```

#### Digital (type 0x00)

```
[low_byte] [high_byte]
Join = (high & 0x7F) << 8 | low
Value = !(high & 0x80)    // bit 7 clear = press/true
```

#### Analog (type 0x14, symmetrical)

```
[channel_hi] [channel_lo] [value_hi] [value_lo]
Channel = 16-bit join number
Value = 0-65535
```

#### Serial (type 0x15)

```
[channel_hi] [channel_lo] [flags] [data...]
Flags: bit 0 = start, bit 1 = end
```

---

## API Reference

### Exceptions

| Exception | Description |
|-----------|-------------|
| `CrestronError` | Base exception |
| `AuthenticationError` | Auth token fetch or CIP auth failed |
| `CrestronConnectionError` | WebSocket or CIP connection issue |
| `ProtocolError` | Malformed packet or unexpected protocol state |
| `CrestronTimeoutError` | Operation timed out |

### Enums

| Enum | Values |
|------|--------|
| `SignalType` | `DIGITAL`, `ANALOG`, `SERIAL` |
| `ConnectionState` | `IDLE`, `CONNECTING`, `WAIT_PROGRAM_READY`, `WAIT_CONNECT_RESPONSE`, `AUTHENTICATING`, `CONNECTED`, `DISCONNECTING`, `RECONNECTING` |

### Data Classes

```python
@dataclass
class SignalEvent:
    signal_type: SignalType    # DIGITAL, ANALOG, or SERIAL
    join: int                  # Join number
    value: bool | int | str    # Signal value
```

### Protocol Functions

All in `pycrestron.protocol`:

| Function | Description |
|----------|-------------|
| `build_cip_packet(type, payload, handle)` | Build a raw CIP packet |
| `build_device_router_connect(ip_id, token, room_id)` | Build handshake packet |
| `build_heartbeat(handle)` | Build heartbeat packet |
| `build_disconnect(handle)` | Build disconnect packet |
| `build_digital_payload(join, value)` | Build digital CRESNET payload |
| `build_analog_payload(join, value)` | Build analog CRESNET payload |
| `build_serial_payload(join, value)` | Build serial CRESNET payload |
| `build_data_packet(handle, cresnet)` | Wrap CRESNET in DATA packet |
| `parse_cip_header(data)` | Parse packet header |
| `parse_cresnet_signals(payload)` | Parse signals from DATA |
| `parse_connect_response(payload)` | Parse connect response |
| `parse_program_ready(payload)` | Parse program ready status |
| `parse_auth_response(payload)` | Parse auth response |

---

## Troubleshooting

### "Connection refused" or timeout

- Verify the processor IP is reachable: `ping 10.11.4.155`
- Confirm WebSocket is enabled on port 49200
- Check that the IP ID exists in the processor's IP Table
- Try with `use_ssl=False` if SSL is not configured

### "Authentication failed"

- Verify username/password on the processor web UI (`https://processor-ip`)
- Try logging in via browser first
- Check that the user has WebSocket access permissions

### "Timed out waiting for PROGRAM_READY"

- The SIMPL/SIMPL# program may not be running on the processor
- Check processor status via web UI
- Status 0x00 = firmware loading (wait and retry)
- Status 0x01 = no program running

### No signal feedback received

- Verify joins are connected in the Crestron program
- Check that the XPanel slot IP ID matches your `ip_id` parameter
- Use Layer 1 raw packet monitoring to see what the processor sends

### Frequent disconnections

- Check network stability between Python host and processor
- Monitor heartbeat timeout logs
- Increase `reconnect_interval` if processor is slow to recover

### Enable debug logging

```python
import logging
logging.basicConfig(level=logging.DEBUG)
logging.getLogger("pycrestron").setLevel(logging.DEBUG)
```
