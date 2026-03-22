"""pycrestron exceptions."""


class CrestronError(Exception):
    """Base exception for pycrestron."""


class AuthenticationError(CrestronError):
    """Authentication failed or token fetch error."""


class CrestronConnectionError(CrestronError):
    """WebSocket or CIP connection error."""


class ProtocolError(CrestronError):
    """Malformed CIP packet or unexpected protocol state."""


class CrestronTimeoutError(CrestronError):
    """Operation timed out (heartbeat, connect, etc.)."""
