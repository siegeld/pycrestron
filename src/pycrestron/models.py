"""pycrestron data models."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Union


class SignalType(Enum):
    """Crestron signal types."""
    DIGITAL = "digital"
    ANALOG = "analog"
    SERIAL = "serial"


class ConnectionState(Enum):
    """CIP connection state machine states."""
    IDLE = auto()
    CONNECTING = auto()
    WAIT_PROGRAM_READY = auto()
    WAIT_CONNECT_RESPONSE = auto()
    AUTHENTICATING = auto()
    CONNECTED = auto()
    DISCONNECTING = auto()
    RECONNECTING = auto()


@dataclass
class SignalEvent:
    """A parsed signal feedback event from the processor."""
    signal_type: SignalType
    join: int
    value: Union[bool, int, str]
