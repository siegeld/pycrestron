"""Integration tests for auto-reconnect behavior."""

import asyncio
import sys
import os

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from mock_cp4 import MockCP4
from pycrestron import CrestronClient


async def _start_client_no_ssl(client, port):
    """Start client with SSL disabled and auto-reconnect enabled."""
    from pycrestron.connection import CIPConnection

    original_port = port

    async def patched_do_connect():
        client._conn = CIPConnection(
            "127.0.0.1",
            0x1A,
            port=original_port,
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


@pytest.fixture
async def mock_cp4():
    server = MockCP4()
    await server.start()
    yield server
    await server.stop()


@pytest.mark.asyncio
async def test_reconnect_after_server_disconnect(mock_cp4):
    """Client should auto-reconnect after server drops connection."""
    client = CrestronClient(
        "127.0.0.1",
        0x1A,
        port=mock_cp4.port,
        auto_reconnect=True,
        reconnect_interval=0.5,
        reconnect_max_interval=2.0,
    )

    connect_count = 0
    disconnect_count = 0
    reconnected = asyncio.Event()

    original_on_connected = client._on_connected

    def track_connect():
        nonlocal connect_count
        connect_count += 1
        original_on_connected()
        if connect_count >= 2:
            reconnected.set()

    original_on_disconnected = client._on_disconnected

    def track_disconnect():
        nonlocal disconnect_count
        disconnect_count += 1
        original_on_disconnected()

    client._on_connected = track_connect
    client._on_disconnected = track_disconnect

    await _start_client_no_ssl(client, mock_cp4.port)
    assert client.connected
    assert connect_count == 1

    # Kill the connection
    await mock_cp4.force_disconnect()

    # Wait for reconnect
    await asyncio.wait_for(reconnected.wait(), timeout=10)

    assert connect_count >= 2
    assert disconnect_count >= 1
    assert client.connected

    await client.stop()


@pytest.mark.asyncio
async def test_state_cache_persists_across_reconnect(mock_cp4):
    """State cache should persist across reconnections."""
    mock_cp4.initial_analogs = {1: 12345}

    client = CrestronClient(
        "127.0.0.1",
        0x1A,
        port=mock_cp4.port,
        auto_reconnect=True,
        reconnect_interval=0.5,
    )

    reconnected = asyncio.Event()
    connect_count = 0
    original_on_connected = client._on_connected

    def track_connect():
        nonlocal connect_count
        connect_count += 1
        original_on_connected()
        if connect_count >= 2:
            reconnected.set()

    client._on_connected = track_connect

    await _start_client_no_ssl(client, mock_cp4.port)
    await asyncio.sleep(0.3)

    # Verify initial state
    assert client.get_analog(1) == 12345

    # Set a value that the server doesn't know about in initial dump
    # This simulates cached state
    client._state_cache[("analog", 99)] = 999

    # Kill and reconnect
    mock_cp4.initial_analogs = {1: 54321}  # new value on reconnect
    await mock_cp4.force_disconnect()
    await asyncio.wait_for(reconnected.wait(), timeout=10)
    await asyncio.sleep(0.3)

    # Old cache key should still exist
    assert client._state_cache.get(("analog", 99)) == 999
    # New state dump should update
    assert client.get_analog(1) == 54321

    await client.stop()


@pytest.mark.asyncio
async def test_availability_tracks_reconnect(mock_cp4):
    """Availability should go False then True on reconnect."""
    client = CrestronClient(
        "127.0.0.1",
        0x1A,
        port=mock_cp4.port,
        auto_reconnect=True,
        reconnect_interval=0.5,
    )

    avail_history = []
    client.on_availability_changed = lambda a: avail_history.append(a)

    reconnected = asyncio.Event()
    connect_count = 0
    original_on_connected = client._on_connected

    def track_connect():
        nonlocal connect_count
        connect_count += 1
        original_on_connected()
        if connect_count >= 2:
            reconnected.set()

    client._on_connected = track_connect

    await _start_client_no_ssl(client, mock_cp4.port)
    assert avail_history == [True]

    await mock_cp4.force_disconnect()
    await asyncio.wait_for(reconnected.wait(), timeout=10)

    # Should see: True (connect) → False (disconnect) → True (reconnect)
    assert avail_history == [True, False, True]

    await client.stop()
