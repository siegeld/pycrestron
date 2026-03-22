"""Integration tests for CrestronHub using MockCP4."""

import asyncio

import pytest

from mock_cp4 import MockCP4
from pycrestron import CrestronHub


@pytest.fixture
async def mock_cp4():
    server = MockCP4()
    await server.start()
    yield server
    await server.stop()


async def _start_hub_no_ssl(hub, port):
    """Start hub with SSL disabled."""
    from pycrestron.connection import CIPConnection

    client = hub._client

    async def patched_do_connect():
        client._conn = CIPConnection(
            "127.0.0.1",
            0x1A,
            port=port,
            use_ssl=False,
        )
        client._conn.on_connect = client._on_connected
        client._conn.on_disconnect = client._on_disconnected
        client._conn.on_error = client._on_error
        client._packet_unsub = client._conn.on_packet(client._on_raw_packet)
        await client._conn.connect()

    client._do_connect = patched_do_connect
    client._running = True
    await client._do_connect()


@pytest.mark.asyncio
async def test_hub_register_digital(mock_cp4):
    hub = CrestronHub("127.0.0.1", 0x1A, port=mock_cp4.port)
    results = []
    hub.register_digital(1, lambda v: results.append(v))

    await _start_hub_no_ssl(hub, mock_cp4.port)

    await mock_cp4.send_digital_feedback(1, True)
    await asyncio.sleep(0.2)
    assert results == [True]

    await hub.stop()


@pytest.mark.asyncio
async def test_hub_register_analog(mock_cp4):
    hub = CrestronHub("127.0.0.1", 0x1A, port=mock_cp4.port)
    results = []
    hub.register_analog(5, lambda v: results.append(v))

    await _start_hub_no_ssl(hub, mock_cp4.port)

    await mock_cp4.send_analog_feedback(5, 65535)
    await asyncio.sleep(0.2)
    assert results == [65535]

    await hub.stop()


@pytest.mark.asyncio
async def test_hub_register_serial(mock_cp4):
    hub = CrestronHub("127.0.0.1", 0x1A, port=mock_cp4.port)
    results = []
    hub.register_serial(1, lambda v: results.append(v))

    await _start_hub_no_ssl(hub, mock_cp4.port)

    await mock_cp4.send_serial_feedback(1, "Test")
    await asyncio.sleep(0.2)
    assert results == ["Test"]

    await hub.stop()


@pytest.mark.asyncio
async def test_hub_availability(mock_cp4):
    hub = CrestronHub("127.0.0.1", 0x1A, port=mock_cp4.port)
    avail = []
    hub.on_availability(lambda a: avail.append(a))

    assert not hub.available

    await _start_hub_no_ssl(hub, mock_cp4.port)
    assert hub.available
    assert avail == [True]

    await hub.stop()
    assert not hub.available
    assert avail == [True, False]


@pytest.mark.asyncio
async def test_hub_set_digital(mock_cp4):
    hub = CrestronHub("127.0.0.1", 0x1A, port=mock_cp4.port)
    await _start_hub_no_ssl(hub, mock_cp4.port)

    await hub.set_digital(1, True)
    await asyncio.sleep(0.1)
    assert mock_cp4.received_digitals.get(1) is True

    await hub.stop()


@pytest.mark.asyncio
async def test_hub_press(mock_cp4):
    hub = CrestronHub("127.0.0.1", 0x1A, port=mock_cp4.port)
    await _start_hub_no_ssl(hub, mock_cp4.port)

    await hub.press(2)
    await asyncio.sleep(0.2)
    assert mock_cp4.received_digitals.get(2) is False  # released after press

    await hub.stop()


@pytest.mark.asyncio
async def test_hub_set_analog(mock_cp4):
    hub = CrestronHub("127.0.0.1", 0x1A, port=mock_cp4.port)
    await _start_hub_no_ssl(hub, mock_cp4.port)

    await hub.set_analog(1, 32768)
    await asyncio.sleep(0.1)
    assert mock_cp4.received_analogs.get(1) == 32768

    await hub.stop()


@pytest.mark.asyncio
async def test_hub_set_serial(mock_cp4):
    hub = CrestronHub("127.0.0.1", 0x1A, port=mock_cp4.port)
    await _start_hub_no_ssl(hub, mock_cp4.port)

    await hub.set_serial(1, "Hello HA")
    await asyncio.sleep(0.1)
    assert mock_cp4.received_serials.get(1) == "Hello HA"

    await hub.stop()


@pytest.mark.asyncio
async def test_hub_get_cached(mock_cp4):
    mock_cp4.initial_digitals = {1: True}
    mock_cp4.initial_analogs = {1: 50000}
    mock_cp4.initial_serials = {1: "Cached"}

    hub = CrestronHub("127.0.0.1", 0x1A, port=mock_cp4.port)
    await _start_hub_no_ssl(hub, mock_cp4.port)
    await asyncio.sleep(0.3)

    assert hub.get_digital(1) is True
    assert hub.get_analog(1) == 50000
    assert hub.get_serial(1) == "Cached"

    await hub.stop()


@pytest.mark.asyncio
async def test_hub_unsubscribe_availability(mock_cp4):
    hub = CrestronHub("127.0.0.1", 0x1A, port=mock_cp4.port)
    avail = []
    unsub = hub.on_availability(lambda a: avail.append(a))

    await _start_hub_no_ssl(hub, mock_cp4.port)
    assert avail == [True]

    unsub()

    await hub.stop()
    # Should NOT get False callback after unsub
    assert avail == [True]
