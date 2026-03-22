"""Mock Crestron CP4 processor for integration testing.

Simulates the CIP protocol server side:
- WebSocket server on a local port
- PROGRAM_READY handshake
- DEVICE_ROUTER_CONNECT_RESPONSE
- Heartbeat echo
- Signal feedback (digital/analog/serial)
- Disconnect handling
"""

from __future__ import annotations

import asyncio
import struct
from typing import Callable

import websockets
import websockets.server

from pycrestron.protocol import (
    CIPPacketType,
    CresnetType,
    build_cip_packet,
    parse_cip_header,
)


class MockCP4:
    """Simulates a Crestron CP4 processor for testing."""

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self._host = host
        self._port = port
        self._server: websockets.server.WebSocketServer | None = None
        self._clients: list[websockets.WebSocketServerProtocol] = []
        self._running = False
        self._client_handle = 0x0042

        # Configurable behavior
        self.program_ready_status: int = 2  # 0=loading, 1=not running, 2=ready
        self.require_auth: bool = False
        self.auth_access_level: int = 5
        self.auto_send_state_dump: bool = True
        self.heartbeat_response: bool = True

        # Signals to send on connect (state dump)
        self.initial_digitals: dict[int, bool] = {}
        self.initial_analogs: dict[int, int] = {}
        self.initial_serials: dict[int, str] = {}

        # Callback for received packets
        self.on_client_packet: Callable[[int, bytes], None] | None = None

        # Track received signals from client
        self.received_digitals: dict[int, bool] = {}
        self.received_analogs: dict[int, int] = {}
        self.received_serials: dict[int, str] = {}

    @property
    def port(self) -> int:
        return self._port

    @property
    def url(self) -> str:
        return f"ws://{self._host}:{self._port}"

    async def start(self) -> None:
        """Start the mock processor server."""
        self._running = True
        self._server = await websockets.serve(
            self._handle_client,
            self._host,
            self._port,
            max_size=2**20,
        )
        # Get the actual port (useful when port=0 for random)
        for sock in self._server.sockets:
            addr = sock.getsockname()
            self._port = addr[1]
            break

    async def stop(self) -> None:
        """Stop the mock processor server."""
        self._running = False
        for client in list(self._clients):
            await client.close()
        self._clients.clear()
        if self._server:
            self._server.close()
            await self._server.wait_closed()
            self._server = None

    async def _handle_client(
        self, ws: websockets.WebSocketServerProtocol, path: str
    ) -> None:
        """Handle a single client connection."""
        self._clients.append(ws)
        try:
            # Send PROGRAM_READY
            await self._send_program_ready(ws)

            async for message in ws:
                if isinstance(message, str):
                    continue
                await self._dispatch(ws, message)
        except websockets.exceptions.ConnectionClosed:
            pass
        finally:
            if ws in self._clients:
                self._clients.remove(ws)

    async def _send_program_ready(self, ws: websockets.WebSocketServerProtocol) -> None:
        """Send PROGRAM_READY packet."""
        pkt = build_cip_packet(
            CIPPacketType.PROGRAM_READY,
            bytes([self.program_ready_status]),
        )
        await ws.send(pkt)

    async def _dispatch(
        self, ws: websockets.WebSocketServerProtocol, data: bytes
    ) -> None:
        """Parse and respond to client packets."""
        ptype, length, payload = parse_cip_header(data)

        if self.on_client_packet:
            self.on_client_packet(ptype, payload)

        if ptype == CIPPacketType.DEVICE_ROUTER_CONNECT:
            await self._handle_device_router_connect(ws, payload)
        elif ptype == CIPPacketType.HEARTBEAT:
            if self.heartbeat_response:
                await self._handle_heartbeat(ws, payload)
        elif ptype == CIPPacketType.DISCONNECT:
            await self._handle_disconnect(ws, payload)
        elif ptype == CIPPacketType.DATA:
            self._handle_data(payload)

    async def _handle_device_router_connect(
        self, ws: websockets.WebSocketServerProtocol, payload: bytes
    ) -> None:
        """Respond with DEVICE_ROUTER_CONNECT_RESPONSE."""
        # Response: [handle_hi][handle_lo][mode][flags][extra_flags 4B][model 30B]
        handle = struct.pack(">H", self._client_handle)
        mode = bytes([0x03])
        flags = bytes([0x00])
        extra = bytes(4)
        model = b"MockCP4".ljust(30, b"\x00")

        response = build_cip_packet(
            CIPPacketType.DEVICE_ROUTER_CONNECT_RESPONSE,
            handle + mode + flags + extra + model,
        )
        await ws.send(response)

        # Send initial state dump if configured
        if self.auto_send_state_dump:
            await self._send_state_dump(ws)

    async def _handle_heartbeat(
        self, ws: websockets.WebSocketServerProtocol, payload: bytes
    ) -> None:
        """Echo heartbeat back as HEARTBEAT_RESPONSE."""
        response = build_cip_packet(
            CIPPacketType.HEARTBEAT_RESPONSE,
            payload,  # echo the same payload (includes handle)
        )
        await ws.send(response)

    async def _handle_disconnect(
        self, ws: websockets.WebSocketServerProtocol, payload: bytes
    ) -> None:
        """Respond with DISCONNECT_RESPONSE and close."""
        response = build_cip_packet(
            CIPPacketType.DISCONNECT_RESPONSE,
            payload,
        )
        await ws.send(response)
        await ws.close()

    def _handle_data(self, payload: bytes) -> None:
        """Parse incoming signal data from client."""
        if len(payload) < 2:
            return
        # Skip 2-byte handle
        cresnet = payload[2:]
        pos = 0
        while pos < len(cresnet):
            if pos + 1 >= len(cresnet):
                break
            clen = cresnet[pos]
            if clen == 0:
                break
            if pos + 1 + clen > len(cresnet):
                break
            ctype = cresnet[pos + 1]
            chunk = cresnet[pos + 2: pos + 1 + clen]
            pos += 1 + clen

            if ctype == CresnetType.DIGITAL and len(chunk) >= 2:
                low, high = chunk[0], chunk[1]
                join = ((high & 0x7F) << 8) | low
                value = (high & 0x80) == 0
                self.received_digitals[join] = value
            elif ctype == CresnetType.SYMMETRICAL_ANALOG and len(chunk) >= 4:
                channel = struct.unpack(">H", chunk[0:2])[0]
                value = struct.unpack(">H", chunk[2:4])[0]
                self.received_analogs[channel] = value
            elif ctype == CresnetType.SERIAL and len(chunk) >= 3:
                channel = struct.unpack(">H", chunk[0:2])[0]
                text = chunk[3:].decode("utf-8", errors="replace")
                self.received_serials[channel] = text

    async def _send_state_dump(self, ws: websockets.WebSocketServerProtocol) -> None:
        """Send initial state as DATA packets."""
        for join, value in self.initial_digitals.items():
            await self.send_digital_feedback(join, value, ws=ws)
        for join, value in self.initial_analogs.items():
            await self.send_analog_feedback(join, value, ws=ws)
        for join, value in self.initial_serials.items():
            await self.send_serial_feedback(join, value, ws=ws)

    # ------------------------------------------------------------------
    # Public: send feedback to connected clients
    # ------------------------------------------------------------------

    async def send_digital_feedback(
        self, join: int, value: bool, ws: websockets.WebSocketServerProtocol | None = None
    ) -> None:
        """Send digital feedback to client(s)."""
        low = join & 0xFF
        high = (join >> 8) & 0x7F
        if not value:
            high |= 0x80
        cresnet = bytes([0x03, CresnetType.DIGITAL, low, high])
        pkt = build_cip_packet(
            CIPPacketType.DATA, cresnet, handle=self._client_handle
        )
        await self._broadcast(pkt, ws)

    async def send_analog_feedback(
        self, join: int, value: int, ws: websockets.WebSocketServerProtocol | None = None
    ) -> None:
        """Send analog feedback to client(s)."""
        cresnet = struct.pack(">BBHH", 0x05, CresnetType.SYMMETRICAL_ANALOG, join, value)
        pkt = build_cip_packet(
            CIPPacketType.DATA, cresnet, handle=self._client_handle
        )
        await self._broadcast(pkt, ws)

    async def send_serial_feedback(
        self, join: int, value: str, ws: websockets.WebSocketServerProtocol | None = None
    ) -> None:
        """Send serial feedback to client(s)."""
        data = value.encode("utf-8")
        cresnet_len = 1 + 2 + 1 + len(data)
        cresnet = struct.pack(">BBHB", cresnet_len, CresnetType.SERIAL, join, 0x03) + data
        pkt = build_cip_packet(
            CIPPacketType.DATA, cresnet, handle=self._client_handle
        )
        await self._broadcast(pkt, ws)

    async def force_disconnect(self) -> None:
        """Force-close all client connections (simulate processor reboot)."""
        for client in list(self._clients):
            await client.close()
        self._clients.clear()

    async def _broadcast(
        self,
        data: bytes,
        ws: websockets.WebSocketServerProtocol | None = None,
    ) -> None:
        targets = [ws] if ws else list(self._clients)
        for target in targets:
            try:
                await target.send(data)
            except websockets.exceptions.ConnectionClosed:
                pass
