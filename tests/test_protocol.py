"""Unit tests for pycrestron.protocol — packet building and parsing."""

import struct

from pycrestron.protocol import (
    CIPPacketType,
    CresnetType,
    build_cip_packet,
    build_device_router_connect,
    build_authenticate,
    build_heartbeat,
    build_disconnect,
    build_digital_payload,
    build_analog_payload,
    build_serial_payload,
    build_data_packet,
    parse_cip_header,
    parse_connect_response,
    parse_program_ready,
    parse_auth_response,
    parse_cresnet_signals,
    parse_extended_data_signals,
)
from pycrestron.models import SignalType


# =========================================================================
# Packet builders
# =========================================================================


class TestBuildCIPPacket:
    def test_basic_packet_no_handle(self):
        pkt = build_cip_packet(0x0D, b"\x01\x02")
        assert pkt[0] == 0x0D
        assert struct.unpack(">H", pkt[1:3])[0] == 2
        assert pkt[3:] == b"\x01\x02"

    def test_packet_with_handle(self):
        pkt = build_cip_packet(0x05, b"\xAA", handle=0x1234)
        assert pkt[0] == 0x05
        length = struct.unpack(">H", pkt[1:3])[0]
        assert length == 3  # 2 (handle) + 1 (payload)
        assert pkt[3:5] == b"\x12\x34"  # handle
        assert pkt[5] == 0xAA  # payload

    def test_empty_payload(self):
        pkt = build_cip_packet(0x03, b"", handle=0x0001)
        assert len(pkt) == 5  # 1 type + 2 len + 2 handle
        assert struct.unpack(">H", pkt[1:3])[0] == 2


class TestBuildDigitalPayload:
    def test_press_join_1(self):
        p = build_digital_payload(1, True)
        # join=1 → wire channel=0 → low=0x00, high=0x00
        assert p == bytes([0x03, 0x00, 0x00, 0x00])

    def test_release_join_1(self):
        p = build_digital_payload(1, False)
        # join=1 → wire channel=0 → low=0x00, high=0x80
        assert p == bytes([0x03, 0x00, 0x00, 0x80])

    def test_press_join_256(self):
        # join=256 → wire channel=255 → low=0xFF, high=0x00
        p = build_digital_payload(256, True)
        assert p == bytes([0x03, 0x00, 0xFF, 0x00])

    def test_release_join_256(self):
        p = build_digital_payload(256, False)
        assert p == bytes([0x03, 0x00, 0xFF, 0x80])

    def test_press_join_5(self):
        p = build_digital_payload(5, True)
        # join=5 → wire channel=4 → low=0x04, high=0x00
        assert p == bytes([0x03, 0x00, 0x04, 0x00])


class TestBuildAnalogPayload:
    def test_zero(self):
        p = build_analog_payload(1, 0)
        # join=1 → wire channel=0
        assert p == bytes([0x05, 0x14, 0x00, 0x00, 0x00, 0x00])

    def test_max(self):
        p = build_analog_payload(1, 65535)
        assert p == bytes([0x05, 0x14, 0x00, 0x00, 0xFF, 0xFF])

    def test_half(self):
        p = build_analog_payload(1, 32768)
        assert p == bytes([0x05, 0x14, 0x00, 0x00, 0x80, 0x00])

    def test_clamp_negative(self):
        p = build_analog_payload(1, -100)
        # should clamp to 0
        assert p[4:6] == b"\x00\x00"

    def test_clamp_overflow(self):
        p = build_analog_payload(1, 70000)
        # should clamp to 65535
        assert p[4:6] == b"\xFF\xFF"

    def test_high_join(self):
        p = build_analog_payload(300, 100)
        channel = struct.unpack(">H", p[2:4])[0]
        assert channel == 299  # join 300 → wire channel 299


class TestBuildSerialPayload:
    def test_simple(self):
        p = build_serial_payload(1, "Hi")
        # len byte = 1(type) + 2(channel) + 1(flags) + 2(data) = 6
        assert p[0] == 6
        assert p[1] == CresnetType.SERIAL
        assert struct.unpack(">H", p[2:4])[0] == 0  # join=1 → wire channel=0
        assert p[4] == 0x03  # start + end flags
        assert p[5:] == b"Hi"

    def test_unicode(self):
        p = build_serial_payload(1, "café")
        data = p[5:]
        assert data == "café".encode("utf-8")


class TestBuildDataPacket:
    def test_wraps_payload(self):
        cresnet = build_digital_payload(1, True)
        pkt = build_data_packet(0x0000, cresnet)
        assert pkt[0] == CIPPacketType.DATA
        length = struct.unpack(">H", pkt[1:3])[0]
        assert length == 2 + len(cresnet)  # handle + cresnet


class TestBuildDeviceRouterConnect:
    def test_basic(self):
        pkt = build_device_router_connect(0x1A)
        assert pkt[0] == CIPPacketType.DEVICE_ROUTER_CONNECT
        # Should be 213 base + 3 header + variable
        assert len(pkt) > 200

    def test_with_token(self):
        pkt_no_token = build_device_router_connect(0x1A)
        pkt_with_token = build_device_router_connect(0x1A, auth_token="mytoken")
        assert len(pkt_with_token) > len(pkt_no_token)

    def test_with_room_id(self):
        pkt = build_device_router_connect(0x1A, room_id="TestRoom")
        # room_id is in the program_name field (32 bytes)
        assert len(pkt) > 200


class TestBuildHeartbeat:
    def test_basic(self):
        pkt = build_heartbeat(0x0001)
        assert pkt[0] == CIPPacketType.HEARTBEAT
        assert pkt[3:5] == b"\x00\x01"


class TestBuildDisconnect:
    def test_basic(self):
        pkt = build_disconnect(0x0001)
        assert pkt[0] == CIPPacketType.DISCONNECT
        assert pkt[3:5] == b"\x00\x01"


class TestBuildAuthenticate:
    def test_basic(self):
        pkt = build_authenticate(0x0001, "my-jwt-token")
        assert pkt[0] == CIPPacketType.AUTHENTICATE
        # handle + token
        assert b"my-jwt-token" in pkt


# =========================================================================
# Packet parsers
# =========================================================================


class TestParseCIPHeader:
    def test_basic(self):
        data = bytes([0x05, 0x00, 0x04, 0xAA, 0xBB, 0xCC, 0xDD])
        ptype, length, payload = parse_cip_header(data)
        assert ptype == 0x05
        assert length == 4
        assert payload == bytes([0xAA, 0xBB, 0xCC, 0xDD])

    def test_empty_payload(self):
        data = bytes([0x0D, 0x00, 0x00])
        ptype, length, payload = parse_cip_header(data)
        assert ptype == 0x0D
        assert length == 0
        assert payload == b""

    def test_too_short(self):
        import pytest
        with pytest.raises(ValueError):
            parse_cip_header(bytes([0x05, 0x00]))


class TestParseConnectResponse:
    def test_basic(self):
        payload = bytes([0x00, 0x42, 0x03])
        handle, mode = parse_connect_response(payload)
        assert handle == 0x0042
        assert mode == 0x03

    def test_too_short(self):
        import pytest
        with pytest.raises(ValueError):
            parse_connect_response(bytes([0x00, 0x01]))


class TestParseProgramReady:
    def test_ready(self):
        assert parse_program_ready(bytes([0x02])) == 2

    def test_loading(self):
        assert parse_program_ready(bytes([0x00])) == 0

    def test_not_running(self):
        assert parse_program_ready(bytes([0x01])) == 1


class TestParseAuthResponse:
    def test_success(self):
        # [handle_hi, handle_lo, access_level]
        payload = bytes([0x00, 0x01, 0x05])
        assert parse_auth_response(payload) == 5

    def test_failure(self):
        payload = bytes([0x00, 0x01, 0x00])
        assert parse_auth_response(payload) == 0


# =========================================================================
# CRESNET signal parsing
# =========================================================================


class TestParseCresnetSignals:
    def test_digital_press(self):
        # Wire channel 4 → join 5 (0-based wire + 1)
        data = bytes([0x03, 0x00, 0x04, 0x00])
        events = parse_cresnet_signals(data)
        assert len(events) == 1
        assert events[0].signal_type == SignalType.DIGITAL
        assert events[0].join == 5
        assert events[0].value is True

    def test_digital_release(self):
        # Wire channel 4, high bit set → release
        data = bytes([0x03, 0x00, 0x04, 0x80])
        events = parse_cresnet_signals(data)
        assert len(events) == 1
        assert events[0].value is False

    def test_digital_high_join(self):
        # Wire channel 299 (0x012B) → join 300. low=0x2B, high=0x01
        data = bytes([0x03, 0x00, 0x2B, 0x01])
        events = parse_cresnet_signals(data)
        assert events[0].join == 300
        assert events[0].value is True

    def test_digital_high_join_release(self):
        data = bytes([0x03, 0x00, 0x2B, 0x81])
        events = parse_cresnet_signals(data)
        assert events[0].join == 300
        assert events[0].value is False

    def test_symmetrical_analog(self):
        # Wire channel 0 → join 1
        data = bytes([0x05, 0x14, 0x00, 0x00, 0x7F, 0xFF])
        events = parse_cresnet_signals(data)
        assert len(events) == 1
        assert events[0].signal_type == SignalType.ANALOG
        assert events[0].join == 1
        assert events[0].value == 32767

    def test_analog_zero(self):
        data = bytes([0x05, 0x14, 0x00, 0x00, 0x00, 0x00])
        events = parse_cresnet_signals(data)
        assert events[0].value == 0

    def test_analog_max(self):
        data = bytes([0x05, 0x14, 0x00, 0x00, 0xFF, 0xFF])
        events = parse_cresnet_signals(data)
        assert events[0].value == 65535

    def test_serial(self):
        # Wire channel 0 → join 1
        text = b"Hello"
        cresnet_len = 1 + 2 + 1 + len(text)
        data = struct.pack(">BBHB", cresnet_len, 0x15, 0, 0x03) + text
        events = parse_cresnet_signals(data)
        assert len(events) == 1
        assert events[0].signal_type == SignalType.SERIAL
        assert events[0].join == 1
        assert events[0].value == "Hello"

    def test_multiple_signals(self):
        """Multiple CRESNET sub-packets in one payload."""
        # Digital wire channel 0 → join 1
        d1 = bytes([0x03, 0x00, 0x00, 0x00])
        # Analog wire channel 1 → join 2
        a1 = bytes([0x05, 0x14, 0x00, 0x01, 0x03, 0xE8])
        data = d1 + a1
        events = parse_cresnet_signals(data)
        assert len(events) == 2
        assert events[0].signal_type == SignalType.DIGITAL
        assert events[0].join == 1
        assert events[1].signal_type == SignalType.ANALOG
        assert events[1].join == 2
        assert events[1].value == 1000

    def test_command_packet_skipped(self):
        # Command type 0x03 with end-of-update (0x16)
        data = bytes([0x02, 0x03, 0x16])
        events = parse_cresnet_signals(data)
        assert len(events) == 0

    def test_empty_payload(self):
        events = parse_cresnet_signals(b"")
        assert len(events) == 0

    def test_zero_length_terminates(self):
        data = bytes([0x00, 0x00, 0x05, 0x00])
        events = parse_cresnet_signals(data)
        assert len(events) == 0

    def test_type_01_analog_4byte(self):
        """Type 0x01 analog with 2-byte channel + 2-byte value."""
        # Wire channel 2 → join 3
        data = bytes([0x05, 0x01, 0x00, 0x02, 0x12, 0x34])
        events = parse_cresnet_signals(data)
        assert len(events) == 1
        assert events[0].signal_type == SignalType.ANALOG
        assert events[0].join == 3
        assert events[0].value == 0x1234


class TestParseExtendedDataSignals:
    def test_extended_serial(self):
        text = b"Extended"
        inner = struct.pack(">BHB", 0x34, 1, 0x03) + text
        cresnet_len = len(inner)
        data = struct.pack(">H", cresnet_len) + inner
        events = parse_extended_data_signals(data)
        assert len(events) == 1
        assert events[0].signal_type == SignalType.SERIAL
        assert events[0].value == "Extended"


# =========================================================================
# Round-trip tests
# =========================================================================


class TestRoundTrips:
    def test_digital_roundtrip(self):
        """Build a digital DATA packet, parse it back."""
        cresnet = build_digital_payload(42, True)
        pkt = build_data_packet(0x0000, cresnet)
        ptype, length, payload = parse_cip_header(pkt)
        assert ptype == CIPPacketType.DATA
        events = parse_cresnet_signals(payload[2:])  # skip handle
        assert len(events) == 1
        assert events[0].join == 42
        assert events[0].value is True

    def test_digital_release_roundtrip(self):
        cresnet = build_digital_payload(42, False)
        pkt = build_data_packet(0x0000, cresnet)
        _, _, payload = parse_cip_header(pkt)
        events = parse_cresnet_signals(payload[2:])
        assert events[0].join == 42
        assert events[0].value is False

    def test_analog_roundtrip(self):
        cresnet = build_analog_payload(10, 12345)
        pkt = build_data_packet(0x0000, cresnet)
        _, _, payload = parse_cip_header(pkt)
        events = parse_cresnet_signals(payload[2:])
        assert len(events) == 1
        assert events[0].join == 10
        assert events[0].value == 12345

    def test_serial_roundtrip(self):
        cresnet = build_serial_payload(7, "test string")
        pkt = build_data_packet(0x0000, cresnet)
        _, _, payload = parse_cip_header(pkt)
        events = parse_cresnet_signals(payload[2:])
        assert len(events) == 1
        assert events[0].join == 7
        assert events[0].value == "test string"
