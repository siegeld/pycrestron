"""CIP packet building/parsing, enums, and constants.

Pure functions — no I/O, fully testable.
"""

from __future__ import annotations

import struct
from enum import IntEnum
from typing import Union

from .models import SignalEvent, SignalType


# ---------------------------------------------------------------------------
# CIP packet type codes
# ---------------------------------------------------------------------------

class CIPPacketType(IntEnum):
    CONNECT = 0x01
    CONNECT_RESPONSE = 0x02
    DISCONNECT = 0x03
    DISCONNECT_RESPONSE = 0x04
    DATA = 0x05
    CONNECT_DHCP = 0x0A
    AUTHENTICATE = 0x0B
    AUTHENTICATE_RESPONSE = 0x0C
    HEARTBEAT = 0x0D
    HEARTBEAT_RESPONSE = 0x0E
    PROGRAM_READY = 0x0F
    CRESNET_DATA = 0x10
    EXTENDED_DATA = 0x12
    CRPC_CONNECT = 0x13
    CRPC_DATA = 0x14
    GENERAL_RCB = 0x1E
    DEVICE_ROUTER_CONNECT = 0x26
    DEVICE_ROUTER_CONNECT_RESPONSE = 0x27
    LICENSE_INFO_RESPONSE = 0x2A


# ---------------------------------------------------------------------------
# CRESNET sub-types inside DATA payloads
# ---------------------------------------------------------------------------

class CresnetType(IntEnum):
    DIGITAL = 0x00
    ANALOG = 0x01
    COMMAND = 0x03
    TIME_AND_DATE = 0x08
    SYMMETRICAL_ANALOG = 0x14
    SERIAL = 0x15
    REPEAT_DIGITAL = 0x27
    GENERAL_RCB = 0x1E
    EXTENDED_SERIAL = 0x34
    SMART_OBJECT = 0x38
    EXTENDED_SMART_OBJECT = 0x39


# ---------------------------------------------------------------------------
# Connection mode/flag constants
# ---------------------------------------------------------------------------

# Connect mode flags
CONNECT_HEARTBEAT = 0x40

# Type flags — exact values from CH5 WebXPanel JS
TYPE_SERIAL_SIZE_256 = 0x01  # K
TYPE_RCB = 0x20              # part of Q
TYPE_HEARTBEAT = 0x10        # part of Q
TYPE_EXTENDED_LENGTH = 0x40  # z
TYPE_UNICODE = 0x80          # q

# Extra flags — exact values from CH5 WebXPanel JS
EXTRA_PROGRAM_INSTANCE_ID = 0x01  # $
EXTRA_AUTHENTICATE = 0x10         # ee
EXTRA_TOKEN_SOURCE = 0x20         # te
EXTRA_AUTH_TOKEN_DATA = 0x40      # ne

# Default connection parameters (match CH5 WebXPanel exactly)
DEFAULT_MODE = CONNECT_HEARTBEAT  # 0x40
DEFAULT_TYPE_HI = (               # K + q + z + Q = 0xF1
    TYPE_SERIAL_SIZE_256
    | TYPE_UNICODE
    | TYPE_EXTENDED_LENGTH
    | TYPE_HEARTBEAT
    | TYPE_RCB
)
DEFAULT_TYPE_LO = 0x01            # Z


# ---------------------------------------------------------------------------
# Packet builders
# ---------------------------------------------------------------------------

def build_cip_packet(packet_type: int, payload: bytes, handle: int | None = None) -> bytes:
    """Build a complete CIP packet: [type][len_hi][len_lo][payload].

    If *handle* is not None it is prepended to *payload* as 2 big-endian bytes
    (included in the length field).
    """
    if handle is not None:
        payload = struct.pack(">H", handle) + payload
    length = len(payload)
    return struct.pack(">BH", packet_type, length) + payload


def build_device_router_connect(
    ip_id: int,
    auth_token: str | None = None,
    room_id: str = "",
) -> bytes:
    """Build DEVICE_ROUTER_CONNECT (0x26) payload.

    Layout (213 fixed bytes + variable auth):
      [ip_id 2B][mode 1B][type 2B][extra_flags 4B][mac 6B]
      [device_make 50B][device_model 50B][room_id 32B][hostname 64B]
      [auth_len 2B][auth_data ...]
    """
    ip_id_bytes = struct.pack(">H", ip_id)

    mode = DEFAULT_MODE
    type_field = struct.pack(">BB", DEFAULT_TYPE_HI, DEFAULT_TYPE_LO)

    extra_flags = EXTRA_AUTHENTICATE | EXTRA_TOKEN_SOURCE
    if auth_token:
        extra_flags |= EXTRA_AUTH_TOKEN_DATA
    if room_id:
        extra_flags |= EXTRA_PROGRAM_INSTANCE_ID
    extra = struct.pack(">I", extra_flags)

    mac = bytes(6)  # 00:00:00:00:00:00

    device_make = b"Crestron".ljust(50, b"\x00")[:50]
    device_model = b"WebXPanel".ljust(50, b"\x00")[:50]
    program_name = room_id.encode("utf-8")[:32].ljust(32, b"\x00")
    hostname = b"Hostname".ljust(64, b"\x00")[:64]

    # Auth token format: "Crestron:<tokenSource>:<jwt>"
    auth_data = b""
    if auth_token:
        auth_str = f"Crestron:CSSelf:{auth_token}"
        auth_data = auth_str.encode("utf-8")
    auth_len = struct.pack(">H", len(auth_data))

    payload = (
        ip_id_bytes
        + struct.pack("B", mode)
        + type_field
        + extra
        + mac
        + device_make
        + device_model
        + program_name
        + hostname
        + auth_len
        + auth_data
    )

    return build_cip_packet(CIPPacketType.DEVICE_ROUTER_CONNECT, payload)


def build_authenticate(handle: int, token: str) -> bytes:
    """Build AUTHENTICATE (0x0B) packet."""
    return build_cip_packet(
        CIPPacketType.AUTHENTICATE,
        token.encode("utf-8"),
        handle=handle,
    )


def build_heartbeat(handle: int) -> bytes:
    """Build HEARTBEAT (0x0D) packet."""
    return build_cip_packet(CIPPacketType.HEARTBEAT, b"", handle=handle)


def build_disconnect(handle: int) -> bytes:
    """Build DISCONNECT (0x03) packet."""
    return build_cip_packet(CIPPacketType.DISCONNECT, b"", handle=handle)


def build_digital_payload(join: int, value: bool) -> bytes:
    """Build a DATA (0x05) packet for a digital join press/release.

    Joins are 1-based externally but 0-based on the wire.
    Join encoding: low_byte = channel & 0xFF, high_byte = (channel >> 8) & 0x7F.
    Press: high_byte bit 7 clear.  Release: high_byte bit 7 set.
    """
    channel = join - 1  # 1-based join → 0-based wire channel
    low = channel & 0xFF
    high = (channel >> 8) & 0x7F
    if not value:
        high |= 0x80
    cresnet = bytes([0x03, CresnetType.DIGITAL, low, high])
    return cresnet


def build_analog_payload(join: int, value: int) -> bytes:
    """Build CRESNET payload for a symmetrical analog join (type 0x14).

    Joins are 1-based externally but 0-based on the wire.
    """
    channel = join - 1  # 1-based join → 0-based wire channel
    value = max(0, min(65535, value))
    cresnet = struct.pack(">BBHH", 0x05, CresnetType.SYMMETRICAL_ANALOG, channel, value)
    return cresnet


def build_serial_payload(join: int, value: str) -> bytes:
    """Build CRESNET payload for a serial join (type 0x15).

    Joins are 1-based externally but 0-based on the wire.
    Flags 0x03 = start + end (single-shot message).
    """
    channel = join - 1  # 1-based join → 0-based wire channel
    data = value.encode("utf-8")
    # length byte = 1(type) + 2(channel) + 1(flags) + len(data)
    cresnet_len = 1 + 2 + 1 + len(data)
    buf = struct.pack(">BBHB", cresnet_len, CresnetType.SERIAL, channel, 0x03) + data
    return buf


def build_data_packet(handle: int, cresnet_payload: bytes) -> bytes:
    """Wrap a CRESNET payload in a CIP DATA (0x05) packet."""
    return build_cip_packet(CIPPacketType.DATA, cresnet_payload, handle=handle)


def build_update_request(handle: int) -> bytes:
    """Build an UPDATE_REQUEST — tells the processor to send all join states.

    Must be sent after CONNECT_RESPONSE to receive feedback.
    Payload: [0x02][0x03][0x00] = CRESNET command "update request".
    """
    return build_cip_packet(
        CIPPacketType.DATA, b"\x02\x03\x00", handle=handle
    )


def build_update_request_response(handle: int) -> bytes:
    """Build END_OF_JOIN_STATUS_RESPONSE (0x1D).

    Sent in response to END_OF_JOIN_STATUS_QUERY (0x1C) from the processor.
    """
    return build_cip_packet(
        CIPPacketType.DATA, b"\x02\x03\x1d", handle=handle
    )


# ---------------------------------------------------------------------------
# Packet parsers
# ---------------------------------------------------------------------------

def parse_cip_header(data: bytes) -> tuple[int, int, bytes]:
    """Parse a CIP packet header.

    Returns (packet_type, length, payload).
    *payload* is everything after the 3-byte header.
    """
    if len(data) < 3:
        raise ValueError(f"CIP packet too short: {len(data)} bytes")
    packet_type = data[0]
    length = struct.unpack(">H", data[1:3])[0]
    payload = data[3: 3 + length]
    return packet_type, length, payload


def parse_connect_response(payload: bytes) -> tuple[int, int]:
    """Parse CONNECT_RESPONSE (0x02) or DEVICE_ROUTER_CONNECT_RESPONSE (0x27).

    Returns (handle, mode).
    """
    if len(payload) < 3:
        raise ValueError(f"Connect response too short: {len(payload)} bytes")
    handle = struct.unpack(">H", payload[0:2])[0]
    mode = payload[2]
    return handle, mode


def parse_program_ready(payload: bytes) -> int:
    """Parse PROGRAM_READY (0x0F) payload.

    Returns status: 0=loading, 1=not running, 2=ready.
    """
    if len(payload) < 1:
        raise ValueError("Program ready payload empty")
    return payload[0]


def parse_auth_response(payload: bytes) -> int:
    """Parse AUTHENTICATE_RESPONSE (0x0C) payload.

    Returns access_level (0 = failed, >0 = success).
    """
    if len(payload) < 3:
        raise ValueError(f"Auth response too short: {len(payload)} bytes")
    # payload: [handle_hi][handle_lo][access_level]
    return payload[2]


def parse_cresnet_signals(payload: bytes) -> list[SignalEvent]:
    """Parse CRESNET sub-packets from a DATA/CRESNET_DATA payload.

    *payload* should start after the 2-byte handle (i.e., the raw CRESNET
    portion of the CIP DATA payload).

    Returns a list of SignalEvent.
    """
    events: list[SignalEvent] = []
    pos = 0
    while pos < len(payload):
        if pos + 1 >= len(payload):
            break
        cresnet_len = payload[pos]
        if cresnet_len == 0:
            break
        if pos + 1 + cresnet_len > len(payload):
            break  # truncated
        cresnet_type = payload[pos + 1]
        chunk = payload[pos + 2: pos + 1 + cresnet_len]
        pos += 1 + cresnet_len

        if cresnet_type == CresnetType.DIGITAL:
            _parse_digital_chunk(chunk, events)
        elif cresnet_type == CresnetType.ANALOG:
            _parse_analog_chunk(chunk, events)
        elif cresnet_type == CresnetType.SYMMETRICAL_ANALOG:
            _parse_sym_analog_chunk(chunk, events)
        elif cresnet_type == CresnetType.SERIAL:
            _parse_serial_chunk(chunk, events)
        elif cresnet_type == CresnetType.REPEAT_DIGITAL:
            _parse_digital_chunk(chunk, events)
        elif cresnet_type == CresnetType.EXTENDED_SERIAL:
            _parse_serial_chunk(chunk, events)
        elif cresnet_type == CresnetType.SMART_OBJECT:
            _parse_smart_object_chunk(chunk, events)
        # Command packets (0x03) are control flow — skip them

    return events


def parse_extended_data_signals(payload: bytes) -> list[SignalEvent]:
    """Parse an EXTENDED_DATA (0x12) payload.

    EXTENDED_DATA uses 2-byte CRESNET length instead of 1-byte.
    *payload* starts after the 2-byte CIP handle.
    """
    events: list[SignalEvent] = []
    pos = 0
    while pos < len(payload):
        if pos + 2 >= len(payload):
            break
        cresnet_len = struct.unpack(">H", payload[pos: pos + 2])[0]
        if cresnet_len == 0:
            break
        if pos + 2 + cresnet_len > len(payload):
            break
        cresnet_type = payload[pos + 2]
        chunk = payload[pos + 3: pos + 2 + cresnet_len]
        pos += 2 + cresnet_len

        if cresnet_type == CresnetType.EXTENDED_SERIAL:
            _parse_serial_chunk(chunk, events)
        elif cresnet_type == CresnetType.SMART_OBJECT:
            _parse_smart_object_chunk(chunk, events)
        elif cresnet_type == CresnetType.EXTENDED_SMART_OBJECT:
            _parse_smart_object_chunk(chunk, events)
        elif cresnet_type == CresnetType.DIGITAL:
            _parse_digital_chunk(chunk, events)
        elif cresnet_type == CresnetType.ANALOG:
            _parse_analog_chunk(chunk, events)
        elif cresnet_type == CresnetType.SYMMETRICAL_ANALOG:
            _parse_sym_analog_chunk(chunk, events)

    return events


# ---------------------------------------------------------------------------
# Internal CRESNET chunk parsers
# ---------------------------------------------------------------------------

def _parse_digital_chunk(chunk: bytes, events: list[SignalEvent]) -> None:
    """Parse digital I/O bytes into SignalEvents.

    Each pair: [low_byte][high_byte].
    Wire channel = (high & 0x7F) << 8 | low (0-based).
    Join = channel + 1 (1-based).  Value = !(high & 0x80).
    """
    i = 0
    while i + 1 < len(chunk):
        low = chunk[i]
        high = chunk[i + 1]
        channel = ((high & 0x7F) << 8) | low
        join = channel + 1  # 0-based wire channel → 1-based join
        value = (high & 0x80) == 0  # bit 7 clear = press/true
        events.append(SignalEvent(SignalType.DIGITAL, join, value))
        i += 2


def _parse_analog_chunk(chunk: bytes, events: list[SignalEvent]) -> None:
    """Parse type-0x01 analog I/O.

    Wire channels are 0-based; joins are 1-based (channel + 1).
    The format depends on the parent cresnet_len:
      len=2 → 1-byte channel, 1-byte value
      len=3 → 1-byte channel, 2-byte value
      len=4 → 2-byte channel, 2-byte value
      len>4 → multi-channel (pairs of channel + 2-byte values)
    """
    n = len(chunk)
    if n == 2:
        events.append(SignalEvent(SignalType.ANALOG, chunk[0] + 1, chunk[1]))
    elif n == 3:
        channel = chunk[0]
        value = struct.unpack(">H", chunk[1:3])[0]
        events.append(SignalEvent(SignalType.ANALOG, channel + 1, value))
    elif n >= 4:
        channel = struct.unpack(">H", chunk[0:2])[0]
        value = struct.unpack(">H", chunk[2:4])[0]
        events.append(SignalEvent(SignalType.ANALOG, channel + 1, value))
        # Multi-channel: remaining pairs
        i = 4
        while i + 3 < n:
            ch = struct.unpack(">H", chunk[i: i + 2])[0]
            val = struct.unpack(">H", chunk[i + 2: i + 4])[0]
            events.append(SignalEvent(SignalType.ANALOG, ch + 1, val))
            i += 4


def _parse_sym_analog_chunk(chunk: bytes, events: list[SignalEvent]) -> None:
    """Parse symmetrical analog (0x14): [channel_hi][channel_lo][value_hi][value_lo].

    Wire channels are 0-based; joins are 1-based (channel + 1).
    """
    if len(chunk) < 4:
        return
    channel = struct.unpack(">H", chunk[0:2])[0]
    value = struct.unpack(">H", chunk[2:4])[0]
    events.append(SignalEvent(SignalType.ANALOG, channel + 1, value))


def _parse_serial_chunk(chunk: bytes, events: list[SignalEvent]) -> None:
    """Parse serial I/O (0x15 or 0x34): [channel_hi][channel_lo][flags][data...].

    Wire channels are 0-based; joins are 1-based (channel + 1).
    """
    if len(chunk) < 3:
        return
    channel = struct.unpack(">H", chunk[0:2])[0]
    # flags = chunk[2]  # bit 0 = start, bit 1 = end
    data = chunk[3:]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    events.append(SignalEvent(SignalType.SERIAL, channel + 1, text))


def _parse_smart_object_chunk(chunk: bytes, events: list[SignalEvent]) -> None:
    """Parse smart object wrapper — contains nested CRESNET packets."""
    # Recursively parse nested packets
    nested_events = parse_cresnet_signals(chunk)
    events.extend(nested_events)
