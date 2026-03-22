"""Layer 1: CIPConnection — raw CIP protocol over WebSocket."""

from __future__ import annotations

import asyncio
import logging
import ssl
from typing import Callable

import websockets
import websockets.exceptions

from .exceptions import CrestronConnectionError, CrestronTimeoutError, ProtocolError
from .models import ConnectionState
from .protocol import (
    CIPPacketType,
    build_analog_payload,
    build_data_packet,
    build_device_router_connect,
    build_digital_payload,
    build_disconnect,
    build_heartbeat,
    build_serial_payload,
    parse_auth_response,
    parse_cip_header,
    parse_connect_response,
    parse_program_ready,
)

_LOGGER = logging.getLogger(__name__)

_HEARTBEAT_INTERVAL = 15.0  # seconds between CIP heartbeats
_CONNECT_TIMEOUT = 30.0  # seconds to wait for full handshake


class CIPConnection:
    """Raw CIP protocol connection over WebSocket."""

    def __init__(
        self,
        host: str,
        ip_id: int,
        *,
        port: int = 49200,
        use_ssl: bool = True,
    ) -> None:
        self._host = host
        self._ip_id = ip_id
        self._port = port
        self._use_ssl = use_ssl

        self._ws: websockets.WebSocketClientProtocol | None = None
        self._state = ConnectionState.IDLE
        self._handle: int = 0
        self._room_id: str = ""

        self._packet_callbacks: list[Callable[[int, bytes], None]] = []
        self._recv_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._last_server_msg: float = 0.0

        # Handshake synchronization
        self._connect_event: asyncio.Event = asyncio.Event()
        self._program_ready_event: asyncio.Event = asyncio.Event()

        # Public event hooks
        self.on_connect: Callable[[], None] | None = None
        self.on_disconnect: Callable[[], None] | None = None
        self.on_error: Callable[[Exception], None] | None = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._state == ConnectionState.CONNECTED

    @property
    def state(self) -> ConnectionState:
        return self._state

    @property
    def handle(self) -> int:
        return self._handle

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def connect(self, auth_token: str | None = None) -> None:
        """Connect WebSocket, complete CIP handshake, start heartbeat."""
        if self._state not in (ConnectionState.IDLE, ConnectionState.RECONNECTING):
            raise CrestronConnectionError(
                f"Cannot connect in state {self._state.name}"
            )

        self._state = ConnectionState.CONNECTING
        self._connect_event.clear()
        self._program_ready_event.clear()

        ssl_ctx: ssl.SSLContext | None = None
        if self._use_ssl:
            ssl_ctx = ssl.create_default_context()
            ssl_ctx.check_hostname = False
            ssl_ctx.verify_mode = ssl.CERT_NONE

        scheme = "wss" if self._use_ssl else "ws"
        uri = f"{scheme}://{self._host}:{self._port}/websocket"

        try:
            self._ws = await websockets.connect(
                uri,
                ssl=ssl_ctx,
                extra_headers={},
                max_size=2**20,
                open_timeout=10,
            )
        except Exception as exc:
            self._state = ConnectionState.IDLE
            raise CrestronConnectionError(
                f"WebSocket connect failed: {exc}"
            ) from exc

        self._last_server_msg = asyncio.get_event_loop().time()
        self._recv_task = asyncio.create_task(self._receive_loop())

        # Wait for PROGRAM_READY
        self._state = ConnectionState.WAIT_PROGRAM_READY
        try:
            await asyncio.wait_for(
                self._program_ready_event.wait(), timeout=_CONNECT_TIMEOUT
            )
        except asyncio.TimeoutError:
            await self._cleanup()
            raise CrestronTimeoutError("Timed out waiting for PROGRAM_READY")

        # Send DEVICE_ROUTER_CONNECT
        self._state = ConnectionState.WAIT_CONNECT_RESPONSE
        dr_packet = build_device_router_connect(
            self._ip_id, auth_token, self._room_id
        )
        await self._send_raw(dr_packet)

        # Wait for connect response (sets _handle) and optional auth
        try:
            await asyncio.wait_for(
                self._connect_event.wait(), timeout=_CONNECT_TIMEOUT
            )
        except asyncio.TimeoutError:
            await self._cleanup()
            raise CrestronTimeoutError("Timed out waiting for CONNECT_RESPONSE")

        # Start heartbeat
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        _LOGGER.info("CIP connected to %s (handle=0x%04x)", self._host, self._handle)
        if self.on_connect:
            self.on_connect()

    async def disconnect(self) -> None:
        """Send DISCONNECT and close cleanly."""
        if self._state == ConnectionState.IDLE:
            return
        self._state = ConnectionState.DISCONNECTING
        try:
            if self._ws and self._ws.open:
                await self._send_raw(build_disconnect(self._handle))
        except Exception:
            pass
        await self._cleanup()
        _LOGGER.info("CIP disconnected from %s", self._host)

    async def _cleanup(self) -> None:
        """Cancel tasks and close WebSocket."""
        if self._heartbeat_task and not self._heartbeat_task.done():
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        self._heartbeat_task = None

        if self._recv_task and not self._recv_task.done():
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
        self._recv_task = None

        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        was_connected = self._state in (
            ConnectionState.CONNECTED,
            ConnectionState.DISCONNECTING,
        )
        self._state = ConnectionState.IDLE

        if was_connected and self.on_disconnect:
            self.on_disconnect()

    # ------------------------------------------------------------------
    # Raw packet I/O
    # ------------------------------------------------------------------

    async def send_packet(self, packet_type: int, payload: bytes = b"") -> None:
        """Send a raw CIP packet. Handle is auto-prepended."""
        from .protocol import build_cip_packet

        packet = build_cip_packet(packet_type, payload, handle=self._handle)
        await self._send_raw(packet)

    def on_packet(self, callback: Callable[[int, bytes], None]) -> Callable:
        """Register callback for incoming CIP packets. Returns unsubscribe fn."""
        self._packet_callbacks.append(callback)

        def unsubscribe() -> None:
            if callback in self._packet_callbacks:
                self._packet_callbacks.remove(callback)

        return unsubscribe

    async def _send_raw(self, data: bytes) -> None:
        """Send raw bytes over WebSocket."""
        if not self._ws:
            raise CrestronConnectionError("Not connected")
        try:
            await self._ws.send(data)
        except websockets.exceptions.ConnectionClosed as exc:
            raise CrestronConnectionError(f"WebSocket closed: {exc}") from exc

    # ------------------------------------------------------------------
    # Convenience senders
    # ------------------------------------------------------------------

    async def send_digital(self, join: int, value: bool) -> None:
        """Send a digital join value."""
        payload = build_digital_payload(join, value)
        await self._send_raw(build_data_packet(self._handle, payload))

    async def send_analog(self, join: int, value: int) -> None:
        """Send an analog join value (0-65535)."""
        payload = build_analog_payload(join, value)
        await self._send_raw(build_data_packet(self._handle, payload))

    async def send_serial(self, join: int, value: str) -> None:
        """Send a serial join string."""
        payload = build_serial_payload(join, value)
        await self._send_raw(build_data_packet(self._handle, payload))

    # ------------------------------------------------------------------
    # Receive loop
    # ------------------------------------------------------------------

    async def _receive_loop(self) -> None:
        """Read and dispatch incoming CIP packets."""
        try:
            assert self._ws is not None
            async for message in self._ws:
                if isinstance(message, str):
                    continue  # CIP is binary
                self._last_server_msg = asyncio.get_event_loop().time()
                await self._dispatch(message)
        except websockets.exceptions.ConnectionClosed:
            _LOGGER.debug("WebSocket closed in receive loop")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            _LOGGER.error("Receive loop error: %s", exc)
            if self.on_error:
                self.on_error(exc)
        finally:
            if self._state == ConnectionState.CONNECTED:
                await self._cleanup()

    async def _dispatch(self, data: bytes) -> None:
        """Parse a CIP packet and handle protocol messages."""
        try:
            packet_type, length, payload = parse_cip_header(data)
        except ValueError as exc:
            _LOGGER.warning("Bad CIP packet: %s", exc)
            return

        # Notify raw packet listeners
        for cb in list(self._packet_callbacks):
            try:
                cb(packet_type, payload)
            except Exception as exc:
                _LOGGER.error("Packet callback error: %s", exc)

        # Protocol state machine
        if packet_type == CIPPacketType.PROGRAM_READY:
            await self._handle_program_ready(payload)
        elif packet_type == CIPPacketType.DEVICE_ROUTER_CONNECT_RESPONSE:
            self._handle_connect_response(payload)
        elif packet_type == CIPPacketType.CONNECT_RESPONSE:
            self._handle_connect_response(payload)
        elif packet_type == CIPPacketType.AUTHENTICATE_RESPONSE:
            self._handle_auth_response(payload)
        elif packet_type == CIPPacketType.HEARTBEAT:
            await self._handle_heartbeat(payload)
        elif packet_type == CIPPacketType.HEARTBEAT_RESPONSE:
            pass  # Server acknowledged our heartbeat — timestamp already updated
        elif packet_type == CIPPacketType.DISCONNECT:
            _LOGGER.info("Server sent DISCONNECT")
            await self._cleanup()

    # ------------------------------------------------------------------
    # Protocol handlers
    # ------------------------------------------------------------------

    async def _handle_program_ready(self, payload: bytes) -> None:
        status = parse_program_ready(payload)
        _LOGGER.debug("PROGRAM_READY status=%d", status)
        if status == 2:
            self._program_ready_event.set()
        elif status == 0:
            _LOGGER.info("Firmware loading, will retry...")
            # Caller's reconnect logic should handle this

    def _handle_connect_response(self, payload: bytes) -> None:
        try:
            handle, mode = parse_connect_response(payload)
        except ValueError as exc:
            _LOGGER.error("Bad connect response: %s", exc)
            return
        self._handle = handle
        _LOGGER.debug("Connect response: handle=0x%04x mode=0x%02x", handle, mode)
        self._state = ConnectionState.CONNECTED
        self._connect_event.set()

    def _handle_auth_response(self, payload: bytes) -> None:
        try:
            access_level = parse_auth_response(payload)
        except ValueError as exc:
            _LOGGER.error("Bad auth response: %s", exc)
            return
        if access_level == 0:
            _LOGGER.error("Authentication failed (access_level=0)")
            if self.on_error:
                self.on_error(
                    ProtocolError("Authentication failed")
                )
        else:
            _LOGGER.info("Authenticated (access_level=%d)", access_level)
            self._state = ConnectionState.CONNECTED
            self._connect_event.set()

    async def _handle_heartbeat(self, payload: bytes) -> None:
        """Respond to server heartbeat with HEARTBEAT_RESPONSE."""
        from .protocol import build_cip_packet

        response = build_cip_packet(
            CIPPacketType.HEARTBEAT_RESPONSE, payload[2:], handle=self._handle
        )
        try:
            await self._send_raw(response)
        except CrestronConnectionError:
            pass

    # ------------------------------------------------------------------
    # Heartbeat loop
    # ------------------------------------------------------------------

    async def _heartbeat_loop(self) -> None:
        """Send periodic CIP heartbeats.

        Liveness is handled by WebSocket-level pings/pongs (managed by the
        websockets library).  CIP heartbeats are sent as a keep-alive signal
        to the processor but we do not timeout on missing responses — some
        Crestron firmware only uses WebSocket keepalive, not CIP heartbeats.
        """
        try:
            while self._state == ConnectionState.CONNECTED:
                await asyncio.sleep(_HEARTBEAT_INTERVAL)
                if self._state != ConnectionState.CONNECTED:
                    break
                try:
                    await self._send_raw(build_heartbeat(self._handle))
                except CrestronConnectionError:
                    await self._cleanup()
                    return
        except asyncio.CancelledError:
            raise

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> CIPConnection:
        await self.connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.disconnect()
