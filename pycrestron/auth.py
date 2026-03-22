"""Auth token fetcher for Crestron processors.

Performs the 3-step login flow:
  1. GET /userlogin.html → extract TRACKID cookie
  2. POST /userlogin.html → login with credentials
  3. GET /cws/websocket/getWebSocketToken → JWT
"""

from __future__ import annotations

import ssl

import aiohttp

from .exceptions import AuthenticationError


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
    base = f"https://{host}:{port}"

    ssl_ctx: ssl.SSLContext | bool
    if not ssl_verify:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.check_hostname = False
        ssl_ctx.verify_mode = ssl.CERT_NONE
    else:
        ssl_ctx = True

    jar = aiohttp.CookieJar(unsafe=True)
    connector = aiohttp.TCPConnector(ssl=ssl_ctx)

    try:
        async with aiohttp.ClientSession(
            cookie_jar=jar,
            connector=connector,
        ) as session:
            # Step 1: GET login page to obtain TRACKID cookie
            async with session.get(
                f"{base}/userlogin.html",
                allow_redirects=False,
            ) as resp:
                if resp.status not in (200, 301, 302):
                    raise AuthenticationError(
                        f"Failed to fetch login page: HTTP {resp.status}"
                    )

            # Step 2: POST credentials
            async with session.post(
                f"{base}/userlogin.html",
                data={"login": username, "passwd": password},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                allow_redirects=False,
            ) as resp:
                if resp.status not in (200, 301, 302):
                    raise AuthenticationError(
                        f"Login POST failed: HTTP {resp.status}"
                    )

            # Step 3: Fetch WebSocket token
            async with session.get(
                f"{base}/cws/websocket/getWebSocketToken",
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
