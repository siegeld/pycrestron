"""Integration tests for CrestronClient using MockCP4."""

import asyncio
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mock_cp4 import MockCP4
from pycrestron import CrestronClient


@pytest.fixture
async def mock_cp4():
    server = MockCP4()
    await server.start()
    yield server
    await server.stop()


@pytest.fixture
def make_client(mock_cp4):
    """Factory to create a CrestronClient pointed at the mock."""

    def _make(**kwargs):
        defaults = dict(
            auto_reconnect=False,
        )
        defaults.update(kwargs)
        client = CrestronClient(
            "127.0.0.1",
            0x1A,
            port=mock_cp4.port,
            **defaults,
        )
        # Patch connection to not use SSL
        return client

    return _make


async def _start_client_no_ssl(client):
    """Start client with SSL disabled on the underlying connection."""
    # We need to monkey-patch the connection creation to disable SSL
    original_do_connect = client._do_connect

    async def patched_do_connect():
        from pycrestron.connection import CIPConnection

        client._conn = CIPConnection(
            "127.0.0.1",
            0x1A,
            port=client._port,
            use_ssl=False,
        )
        client._conn.on_connect = client._on_connected
        client._conn.on_disconnect = client._on_disconnected
        client._conn.on_error = client._on_error
        client._packet_unsub = client._conn.on_packet(client._on_raw_packet)

        try:
            await client._conn.connect(auth_token=client._auth_token)
        except Exception:
            if client._packet_unsub:
                client._packet_unsub()
                client._packet_unsub = None
            client._conn = None
            raise

    client._do_connect = patched_do_connect
    client._running = True
    await client._do_connect()


@pytest.mark.asyncio
async def test_subscribe_digital_feedback(mock_cp4, make_client):
    client = make_client()
    results = []
    client.subscribe_digital(1, lambda v: results.append(v))

    await _start_client_no_ssl(client)
    assert client.connected

    await mock_cp4.send_digital_feedback(1, True)
    await asyncio.sleep(0.2)
    assert results == [True]

    await mock_cp4.send_digital_feedback(1, False)
    await asyncio.sleep(0.2)
    assert results == [True, False]

    await client.stop()


@pytest.mark.asyncio
async def test_subscribe_analog_feedback(mock_cp4, make_client):
    client = make_client()
    results = []
    client.subscribe_analog(5, lambda v: results.append(v))

    await _start_client_no_ssl(client)

    await mock_cp4.send_analog_feedback(5, 32768)
    await asyncio.sleep(0.2)
    assert results == [32768]

    await mock_cp4.send_analog_feedback(5, 0)
    await asyncio.sleep(0.2)
    assert results == [32768, 0]

    await client.stop()


@pytest.mark.asyncio
async def test_subscribe_serial_feedback(mock_cp4, make_client):
    client = make_client()
    results = []
    client.subscribe_serial(1, lambda v: results.append(v))

    await _start_client_no_ssl(client)

    await mock_cp4.send_serial_feedback(1, "Hello")
    await asyncio.sleep(0.2)
    assert results == ["Hello"]

    await client.stop()


@pytest.mark.asyncio
async def test_state_cache(mock_cp4, make_client):
    client = make_client()
    await _start_client_no_ssl(client)

    # No cached value initially
    assert client.get_digital(1) is None
    assert client.get_analog(1) is None
    assert client.get_serial(1) is None

    await mock_cp4.send_digital_feedback(1, True)
    await mock_cp4.send_analog_feedback(1, 12345)
    await mock_cp4.send_serial_feedback(1, "cached")
    await asyncio.sleep(0.2)

    assert client.get_digital(1) is True
    assert client.get_analog(1) == 12345
    assert client.get_serial(1) == "cached"

    await client.stop()


@pytest.mark.asyncio
async def test_set_digital(mock_cp4, make_client):
    client = make_client()
    await _start_client_no_ssl(client)

    await client.set_digital(3, True)
    await asyncio.sleep(0.1)
    assert mock_cp4.received_digitals.get(3) is True

    await client.set_digital(3, False)
    await asyncio.sleep(0.1)
    assert mock_cp4.received_digitals.get(3) is False

    await client.stop()


@pytest.mark.asyncio
async def test_press(mock_cp4, make_client):
    client = make_client()
    await _start_client_no_ssl(client)

    await client.press(7)
    await asyncio.sleep(0.2)
    # After press, the join should end at False (released)
    assert mock_cp4.received_digitals.get(7) is False

    await client.stop()


@pytest.mark.asyncio
async def test_set_analog(mock_cp4, make_client):
    client = make_client()
    await _start_client_no_ssl(client)

    await client.set_analog(10, 50000)
    await asyncio.sleep(0.1)
    assert mock_cp4.received_analogs.get(10) == 50000

    await client.stop()


@pytest.mark.asyncio
async def test_set_serial(mock_cp4, make_client):
    client = make_client()
    await _start_client_no_ssl(client)

    await client.set_serial(2, "Test String")
    await asyncio.sleep(0.1)
    assert mock_cp4.received_serials.get(2) == "Test String"

    await client.stop()


@pytest.mark.asyncio
async def test_unsubscribe(mock_cp4, make_client):
    client = make_client()
    results = []
    unsub = client.subscribe_digital(1, lambda v: results.append(v))

    await _start_client_no_ssl(client)

    await mock_cp4.send_digital_feedback(1, True)
    await asyncio.sleep(0.2)
    assert len(results) == 1

    unsub()

    await mock_cp4.send_digital_feedback(1, False)
    await asyncio.sleep(0.2)
    assert len(results) == 1  # no new callback

    await client.stop()


@pytest.mark.asyncio
async def test_initial_state_dump(mock_cp4, make_client):
    """Test that server state dump fires subscriber callbacks."""
    mock_cp4.initial_digitals = {1: True, 2: False}
    mock_cp4.initial_analogs = {1: 32768}
    mock_cp4.initial_serials = {1: "Init"}

    client = make_client()
    digital_results = {}
    analog_results = {}
    serial_results = {}

    client.subscribe_digital(1, lambda v: digital_results.update({1: v}))
    client.subscribe_digital(2, lambda v: digital_results.update({2: v}))
    client.subscribe_analog(1, lambda v: analog_results.update({1: v}))
    client.subscribe_serial(1, lambda v: serial_results.update({1: v}))

    await _start_client_no_ssl(client)
    await asyncio.sleep(0.3)

    assert digital_results.get(1) is True
    assert digital_results.get(2) is False
    assert analog_results.get(1) == 32768
    assert serial_results.get(1) == "Init"

    await client.stop()


@pytest.mark.asyncio
async def test_availability_callback(mock_cp4, make_client):
    client = make_client()
    avail_history = []
    client.on_availability_changed = lambda a: avail_history.append(a)

    await _start_client_no_ssl(client)
    assert avail_history == [True]

    await client.stop()
    assert avail_history == [True, False]


@pytest.mark.asyncio
async def test_multiple_subscribers_same_join(mock_cp4, make_client):
    client = make_client()
    results_a = []
    results_b = []
    client.subscribe_digital(1, lambda v: results_a.append(v))
    client.subscribe_digital(1, lambda v: results_b.append(v))

    await _start_client_no_ssl(client)

    await mock_cp4.send_digital_feedback(1, True)
    await asyncio.sleep(0.2)

    assert results_a == [True]
    assert results_b == [True]

    await client.stop()
