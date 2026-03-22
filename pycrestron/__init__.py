"""pycrestron — Pure Python Crestron CIP protocol library.

Three-layer architecture:
  Layer 1: CIPConnection   — raw CIP packets over WebSocket
  Layer 2: CrestronClient  — signal-level subscribe/publish with auto-reconnect
  Layer 3: CrestronHub     — Home Assistant optimized wrapper
"""

from .client import CrestronClient
from .connection import CIPConnection
from .exceptions import (
    AuthenticationError,
    CrestronConnectionError,
    CrestronError,
    CrestronTimeoutError,
    ProtocolError,
)
from .hub import CrestronHub
from .models import ConnectionState, SignalEvent, SignalType

__all__ = [
    "CIPConnection",
    "CrestronClient",
    "CrestronHub",
    "SignalType",
    "ConnectionState",
    "SignalEvent",
    "CrestronError",
    "AuthenticationError",
    "CrestronConnectionError",
    "CrestronTimeoutError",
    "ProtocolError",
]
