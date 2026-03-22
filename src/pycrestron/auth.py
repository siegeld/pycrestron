"""Auth token fetcher for Crestron processors.

Performs the 3-step login flow:
  1. GET /userlogin.html → extract TRACKID cookie
  2. POST /userlogin.html → login with credentials
  3. GET /cws/websocket/getWebSocketToken → JWT
"""

from __future__ import annotations

import re
import ssl

import aiohttp

from .exceptions import AuthenticationError


def _parse_cookies(headers: dict) -> dict[str, str]:
    """Extract cookie name=value pairs from Set-Cookie headers."""
    cookies: dict[str, str] = {}
    for sc in headers.getall("Set-Cookie", []):
        m = re.match(r"^([^=]+)=([^;]*)", sc)
        if m:
            cookies[m.group(1)] = m.group(2)
    return cookies


def _cookie_header(cookies: dict[str, str]) -> str:
    """Build a Cookie header string from name=value pairs."""
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


async def fetch_auth_token(
    host: str,
    username: str,
    password: str,
    *,
    port: int = 443,
    ssl_verify: bool = False,
) -> str:
    """Fetch a WebSocket JWT token from the processor.

    Args:
        host: Processor IP or hostname.
        username: Web UI username.
        password: Web UI password.
        port: HTTPS port (default 443).
        ssl_verify: Verify SSL certificates (default False for self-signed).

    Returns:
        JWT token string for WebSocket authentication.

    Raises:
        AuthenticationError: If any step of the login flow fails.
    """
    # Omit default port from URL so Origin/Referer headers match what
    # the processor expects (it rejects requests with explicit :443).
    if port == 443:
        base = f"https://{host}"
    else:
        base = f"https://{host}:{port}"

    ssl_ctx: ssl.SSLContext | bool
    if not ssl_verify:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
    else:
        ssl_ctx = True

    # Use a dummy cookie jar — we manage cookies manually because
    # aiohttp's jar doesn't reliably send Secure/HttpOnly cookies
    # back to IP-addressed Crestron processors.
    connector = aiohttp.TCPConnector(ssl=ssl_ctx)
    cookies: dict[str, str] = {}

    try:
        async with aiohttp.ClientSession(
            connector=connector,
            cookie_jar=aiohttp.DummyCookieJar(),
        ) as session:
            # Step 1: GET login page to obtain TRACKID cookie
            async with session.get(
                f"{base}/userlogin.html",
            ) as resp:
                if resp.status not in (200, 301, 302):
                    raise AuthenticationError(
                        f"Failed to fetch login page: HTTP {resp.status}"
                    )
                cookies.update(_parse_cookies(resp.headers))

            # Step 2: POST credentials (Referer/Origin required by processor)
            async with session.post(
                f"{base}/userlogin.html",
                data=f"login={username}&passwd={password}",
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Cookie": _cookie_header(cookies),
                    "Referer": f"{base}/userlogin.html",
                    "Origin": base,
                },
                allow_redirects=False,
            ) as resp:
                if resp.status not in (200, 301, 302):
                    raise AuthenticationError(
                        f"Login POST failed: HTTP {resp.status}"
                    )
                cookies.update(_parse_cookies(resp.headers))

            # Step 3: Fetch WebSocket token
            async with session.get(
                f"{base}/cws/websocket/getWebSocketToken",
                headers={"Cookie": _cookie_header(cookies)},
                allow_redirects=False,
            ) as resp:
                if resp.status != 200:
                    raise AuthenticationError(
                        f"Token fetch failed: HTTP {resp.status}"
                    )
                token = await resp.text()

            token = token.strip()
            if not token:
                raise AuthenticationError("Empty token returned")

            return token

    except aiohttp.ClientError as exc:
        raise AuthenticationError(f"HTTP error during auth: {exc}") from exc
