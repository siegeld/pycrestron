"""Layer 2: CrestronClient — signal-level API with auto-reconnect."""

from __future__ import annotations

import asyncio
import logging
from typing import Callable, Union

from .auth import fetch_auth_token
from .connection import CIPConnection
from .exceptions import AuthenticationError, CrestronConnectionError
from .models import ConnectionState, SignalEvent, SignalType
from .protocol import (
    CIPPacketType,
    parse_cip_header,
    parse_cresnet_signals,
    parse_extended_data_signals,
)

_LOGGER = logging.getLogger(__name__)


class CrestronClient:
    """Signal-level Crestron client with auto-reconnect."""

    def __init__(
        self,
        host: str,
        ip_id: int,
        *,
        port: int = 49200,
        auth_token: str | None = None,
        username: str | None = None,
        password: str | None = None,
        auto_reconnect: bool = True,
        reconnect_interval: float = 5.0,
        reconnect_max_interval: float = 300.0,
    ) -> None:
        self._host = host
        self._ip_id = ip_id
        self._port = port
        self._auth_token = auth_token
        self._username = username
        self._password = password
        self._auto_reconnect = auto_reconnect
        self._reconnect_interval = reconnect_interval
        self._reconnect_max_interval = reconnect_max_interval

        self._conn: CIPConnection | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._running = False

        # Signal subscriptions: {(SignalType, join): [callbacks]}
        self._subscriptions: dict[
            tuple[SignalType, int], list[Callable]
        ] = {}

        # State cache: {(SignalType, join): value}
        self._state_cache: dict[
            tuple[SignalType, int], Union[bool, int, str]
        ] = {}

        # Packet callback unsubscribe handle
        self._packet_unsub: Callable | None = None

        # Public event hooks
        self.on_connect: Callable[[], None] | None = None
        self.on_disconnect: Callable[[], None] | None = None
        self.on_availability_changed: Callable[[bool], None] | None = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def connected(self) -> bool:
        return self._conn is not None and self._conn.connected

    @property
    def connection(self) -> CIPConnection:
        """Access the underlying raw connection (Layer 1)."""
        if self._conn is None:
            raise CrestronConnectionError("Not connected")
        return self._conn

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Connect and begin processing."""
        self._running = True
        await self._do_connect()

    async def stop(self) -> None:
        """Disconnect and stop reconnect loop."""
        self._running = False
        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
        self._reconnect_task = None

        if self._conn:
            if self._packet_unsub:
                self._packet_unsub()
                self._packet_unsub = None
            await self._conn.disconnect()
            self._conn = None

    async def _do_connect(self) -> None:
        """Perform a single connection attempt."""
        # Fetch auth token if credentials provided
        token = self._auth_token
        if self._username and self._password:
            try:
                token = await fetch_auth_token(
                    self._host, self._username, self._password
                )
                self._auth_token = token
                _LOGGER.debug("Auth token fetched")
            except AuthenticationError as exc:
                _LOGGER.error("Auth failed: %s", exc)
                if self._auto_reconnect and self._running:
                    self._schedule_reconnect()
                return

        # Create connection
        self._conn = CIPConnection(
            self._host, self._ip_id, port=self._port
        )
        self._conn.on_connect = self._on_connected
        self._conn.on_disconnect = self._on_disconnected
        self._conn.on_error = self._on_error

        # Register packet handler for signal parsing
        self._packet_unsub = self._conn.on_packet(self._on_raw_packet)

        try:
            await self._conn.connect(auth_token=token)
        except (CrestronConnectionError, Exception) as exc:
            _LOGGER.error("Connection failed: %s", exc)
            if self._packet_unsub:
                self._packet_unsub()
                self._packet_unsub = None
            self._conn = None
            if self._auto_reconnect and self._running:
                self._schedule_reconnect()

    # ------------------------------------------------------------------
    # Reconnect
    # ------------------------------------------------------------------

    def _schedule_reconnect(self, delay: float | None = None) -> None:
        """Schedule a reconnect with exponential backoff."""
        if not self._running or not self._auto_reconnect:
            return
        if self._reconnect_task and not self._reconnect_task.done():
            return
        if delay is None:
            delay = self._reconnect_interval
        self._reconnect_task = asyncio.create_task(self._reconnect_loop(delay))

    async def _reconnect_loop(self, initial_delay: float) -> None:
        """Reconnect with exponential backoff."""
        delay = initial_delay
        while self._running and self._auto_reconnect:
            _LOGGER.info("Reconnecting in %.1fs...", delay)
            await asyncio.sleep(delay)
            if not self._running:
                break

            try:
                await self._do_connect()
                if self.connected:
                    return  # Success
            except Exception as exc:
                _LOGGER.error("Reconnect attempt failed: %s", exc)

            delay = min(delay * 2, self._reconnect_max_interval)

    # ------------------------------------------------------------------
    # Internal event handlers
    # ------------------------------------------------------------------

    def _on_connected(self) -> None:
        _LOGGER.info("Connected to %s", self._host)
        if self.on_connect:
            self.on_connect()
        if self.on_availability_changed:
            self.on_availability_changed(True)

    def _on_disconnected(self) -> None:
        _LOGGER.info("Disconnected from %s", self._host)
        if self._packet_unsub:
            self._packet_unsub()
            self._packet_unsub = None

        if self.on_disconnect:
            self.on_disconnect()
        if self.on_availability_changed:
            self.on_availability_changed(False)

        if self._auto_reconnect and self._running:
            # Re-fetch token on reconnect (tokens expire ~5 min)
            self._auth_token = None
            self._schedule_reconnect()

    def _on_error(self, exc: Exception) -> None:
        _LOGGER.error("Connection error: %s", exc)

    # ------------------------------------------------------------------
    # Signal parsing
    # ------------------------------------------------------------------

    def _on_raw_packet(self, packet_type: int, payload: bytes) -> None:
        """Parse CRESNET signals from DATA packets and dispatch to subscribers."""
        if packet_type not in (
            CIPPacketType.DATA,
            CIPPacketType.CRESNET_DATA,
            CIPPacketType.EXTENDED_DATA,
        ):
            return

        if len(payload) < 2:
            return

        # Skip 2-byte handle to get CRESNET data
        cresnet_data = payload[2:]

        if packet_type == CIPPacketType.EXTENDED_DATA:
            events = parse_extended_data_signals(cresnet_data)
        else:
            events = parse_cresnet_signals(cresnet_data)

        for event in events:
            self._dispatch_signal(event)

    def _dispatch_signal(self, event: SignalEvent) -> None:
        """Update cache and notify subscribers."""
        key = (event.signal_type, event.join)
        self._state_cache[key] = event.value

        callbacks = self._subscriptions.get(key, [])
        for cb in list(callbacks):
            try:
                cb(event.value)
            except Exception as exc:
                _LOGGER.error("Signal callback error: %s", exc)

    # ------------------------------------------------------------------
    # Subscribe to feedback (processor → client)
    # ------------------------------------------------------------------

    def subscribe_digital(
        self, join: int, callback: Callable[[bool], None]
    ) -> Callable:
        """Subscribe to digital join feedback. Returns unsubscribe fn."""
        return self._subscribe(SignalType.DIGITAL, join, callback)

    def subscribe_analog(
        self, join: int, callback: Callable[[int], None]
    ) -> Callable:
        """Subscribe to analog join feedback. Returns unsubscribe fn."""
        return self._subscribe(SignalType.ANALOG, join, callback)

    def subscribe_serial(
        self, join: int, callback: Callable[[str], None]
    ) -> Callable:
        """Subscribe to serial join feedback. Returns unsubscribe fn."""
        return self._subscribe(SignalType.SERIAL, join, callback)

    def _subscribe(
        self,
        signal_type: SignalType,
        join: int,
        callback: Callable,
    ) -> Callable:
        key = (signal_type, join)
        if key not in self._subscriptions:
            self._subscriptions[key] = []
        self._subscriptions[key].append(callback)

        def unsubscribe() -> None:
            cbs = self._subscriptions.get(key, [])
            if callback in cbs:
                cbs.remove(callback)

        return unsubscribe

    # ------------------------------------------------------------------
    # Publish signals (client → processor)
    # ------------------------------------------------------------------

    async def set_digital(self, join: int, value: bool) -> None:
        """Set a digital join."""
        if not self.connected:
            raise CrestronConnectionError("Not connected")
        await self._conn.send_digital(join, value)

    async def press(self, join: int) -> None:
        """Momentary press: set True, wait 100ms, set False."""
        await self.set_digital(join, True)
        await asyncio.sleep(0.1)
        await self.set_digital(join, False)

    async def set_analog(self, join: int, value: int) -> None:
        """Set an analog join (0-65535)."""
        if not self.connected:
            raise CrestronConnectionError("Not connected")
        await self._conn.send_analog(join, value)

    async def set_serial(self, join: int, value: str) -> None:
        """Set a serial join string."""
        if not self.connected:
            raise CrestronConnectionError("Not connected")
        await self._conn.send_serial(join, value)

    # ------------------------------------------------------------------
    # State query (last known)
    # ------------------------------------------------------------------

    def get_digital(self, join: int) -> bool | None:
        return self._state_cache.get((SignalType.DIGITAL, join))

    def get_analog(self, join: int) -> int | None:
        return self._state_cache.get((SignalType.ANALOG, join))

    def get_serial(self, join: int) -> str | None:
        return self._state_cache.get((SignalType.SERIAL, join))

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> CrestronClient:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.stop()
