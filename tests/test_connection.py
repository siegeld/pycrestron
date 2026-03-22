"""Integration tests for CIPConnection using MockCP4."""

import asyncio

import pytest

from mock_cp4 import MockCP4
from pycrestron import CIPConnection, ConnectionState
from pycrestron.protocol import CIPPacketType


@pytest.fixture
async def mock_cp4():
    server = MockCP4()
    await server.start()
    yield server
    await server.stop()


@pytest.fixture
def make_conn(mock_cp4):
    """Factory to create a CIPConnection pointed at the mock."""

    def _make(**kwargs):
        return CIPConnection(
            "127.0.0.1",
            0x1A,
            port=mock_cp4.port,
            use_ssl=False,
            **kwargs,
        )

    return _make


@pytest.mark.asyncio
async def test_connect_and_disconnect(mock_cp4, make_conn):
    conn = make_conn()
    await conn.connect()
    assert conn.connected
    assert conn.state == ConnectionState.CONNECTED
    assert conn.handle == 0x0042

    await conn.disconnect()
    assert not conn.connected
    assert conn.state == ConnectionState.IDLE


@pytest.mark.asyncio
async def test_context_manager(mock_cp4, make_conn):
    conn = make_conn()
    async with conn:
        assert conn.connected
    assert not conn.connected


@pytest.mark.asyncio
async def test_send_digital(mock_cp4, make_conn):
    async with make_conn() as conn:
        await conn.send_digital(1, True)
        await asyncio.sleep(0.1)
        assert mock_cp4.received_digitals.get(1) is True

        await conn.send_digital(1, False)
        await asyncio.sleep(0.1)
        assert mock_cp4.received_digitals.get(1) is False


@pytest.mark.asyncio
async def test_send_analog(mock_cp4, make_conn):
    async with make_conn() as conn:
        await conn.send_analog(5, 32768)
        await asyncio.sleep(0.1)
        assert mock_cp4.received_analogs.get(5) == 32768


@pytest.mark.asyncio
async def test_send_serial(mock_cp4, make_conn):
    async with make_conn() as conn:
        await conn.send_serial(1, "Hello CP4")
        await asyncio.sleep(0.1)
        assert mock_cp4.received_serials.get(1) == "Hello CP4"


@pytest.mark.asyncio
async def test_on_packet_callback(mock_cp4, make_conn):
    received = []

    async with make_conn() as conn:
        unsub = conn.on_packet(lambda ptype, data: received.append(ptype))

        # Trigger server to send us feedback
        await mock_cp4.send_digital_feedback(1, True)
        await asyncio.sleep(0.2)

        assert CIPPacketType.DATA in received

        unsub()
        received.clear()

        await mock_cp4.send_digital_feedback(2, False)
        await asyncio.sleep(0.2)
        # After unsub, should still get heartbeat etc. but not via our callback
        # Actually the callback is removed, so received should be empty of new DATA
        assert CIPPacketType.DATA not in received


@pytest.mark.asyncio
async def test_on_connect_event(mock_cp4, make_conn):
    connected_flag = asyncio.Event()
    conn = make_conn()
    conn.on_connect = lambda: connected_flag.set()

    await conn.connect()
    assert connected_flag.is_set()
    await conn.disconnect()


@pytest.mark.asyncio
async def test_on_disconnect_event(mock_cp4, make_conn):
    disconnected_flag = asyncio.Event()
    conn = make_conn()
    conn.on_disconnect = lambda: disconnected_flag.set()

    await conn.connect()
    await conn.disconnect()
    assert disconnected_flag.is_set()


@pytest.mark.asyncio
async def test_server_force_disconnect(mock_cp4, make_conn):
    disconnected = asyncio.Event()
    conn = make_conn()
    conn.on_disconnect = lambda: disconnected.set()

    await conn.connect()
    assert conn.connected

    # Simulate processor reboot
    await mock_cp4.force_disconnect()
    await asyncio.wait_for(disconnected.wait(), timeout=5)
    assert not conn.connected


@pytest.mark.asyncio
async def test_program_ready_loading(mock_cp4, make_conn):
    """Test that connection times out if processor never becomes ready."""
    mock_cp4.program_ready_status = 0  # firmware loading
    conn = make_conn()

    with pytest.raises(Exception):  # TimeoutError or CrestronTimeoutError
        await asyncio.wait_for(conn.connect(), timeout=5)

    await conn.disconnect()
