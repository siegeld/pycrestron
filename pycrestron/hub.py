"""Layer 3: CrestronHub — Home Assistant optimized wrapper."""

from __future__ import annotations

import logging
from typing import Callable

from .client import CrestronClient

_LOGGER = logging.getLogger(__name__)


class CrestronHub:
    """HA-optimized hub. Manages a CrestronClient and provides
    entity-oriented signal registration."""

    def __init__(
        self,
        host: str,
        ip_id: int,
        *,
        port: int = 49200,
        username: str | None = None,
        password: str | None = None,
        auth_token: str | None = None,
    ) -> None:
        self._client = CrestronClient(
            host,
            ip_id,
            port=port,
            username=username,
            password=password,
            auth_token=auth_token,
            auto_reconnect=True,
        )
        self._available = False
        self._availability_callbacks: list[Callable[[bool], None]] = []

        self._client.on_availability_changed = self._on_availability_changed

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def available(self) -> bool:
        """Is the processor connection active? For HA entity availability."""
        return self._available

    @property
    def client(self) -> CrestronClient:
        """Access underlying client for direct signal ops."""
        return self._client

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Connect and begin processing."""
        await self._client.start()

    async def stop(self) -> None:
        """Disconnect and stop reconnect loop."""
        await self._client.stop()
        self._available = False

    # ------------------------------------------------------------------
    # HA-style registration
    # ------------------------------------------------------------------

    def register_digital(
        self, join: int, callback: Callable[[bool], None]
    ) -> Callable:
        """Register a callback for digital join feedback. Returns unsubscribe fn."""
        return self._client.subscribe_digital(join, callback)

    def register_analog(
        self, join: int, callback: Callable[[int], None]
    ) -> Callable:
        """Register a callback for analog join feedback. Returns unsubscribe fn."""
        return self._client.subscribe_analog(join, callback)

    def register_serial(
        self, join: int, callback: Callable[[str], None]
    ) -> Callable:
        """Register a callback for serial join feedback. Returns unsubscribe fn."""
        return self._client.subscribe_serial(join, callback)

    def on_availability(self, callback: Callable[[bool], None]) -> Callable:
        """Register availability callback. Returns unsubscribe fn."""
        self._availability_callbacks.append(callback)

        def unsubscribe() -> None:
            if callback in self._availability_callbacks:
                self._availability_callbacks.remove(callback)

        return unsubscribe

    # ------------------------------------------------------------------
    # Convenience (delegates to client)
    # ------------------------------------------------------------------

    async def set_digital(self, join: int, value: bool) -> None:
        await self._client.set_digital(join, value)

    async def press(self, join: int) -> None:
        await self._client.press(join)

    async def set_analog(self, join: int, value: int) -> None:
        await self._client.set_analog(join, value)

    async def set_serial(self, join: int, value: str) -> None:
        await self._client.set_serial(join, value)

    def get_digital(self, join: int) -> bool | None:
        return self._client.get_digital(join)

    def get_analog(self, join: int) -> int | None:
        return self._client.get_analog(join)

    def get_serial(self, join: int) -> str | None:
        return self._client.get_serial(join)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_availability_changed(self, available: bool) -> None:
        self._available = available
        _LOGGER.info("Processor %s", "available" if available else "unavailable")
        for cb in list(self._availability_callbacks):
            try:
                cb(available)
            except Exception as exc:
                _LOGGER.error("Availability callback error: %s", exc)
