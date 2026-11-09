"""Cross-site request forgery: only the app's own pages may change anything.

The session cookie is SameSite=Lax, which stops other *sites* — but every subdomain of
the same registrable domain is the same site to a browser, and Lax sends the cookie
with their POSTs. On the server this runs on, several other apps share the domain, so
script on any of them could post to `/use` (zeroing a card) or sign every device out.

So a state-changing request from a browser must come from a trusted origin: the one in
WEBAPP_URL, plus any listed in TRUSTED_ORIGINS. Sibling subdomains are never implied.

  * `Origin` present — browsers send it with every POST, PATCH and DELETE, same-origin
    included — and not trusted (or `null`): refused.
  * `Origin` absent but `Sec-Fetch-Site` says another site sent it: refused.
  * Neither header: not a browser (curl, the tests, a script). Such a client cannot
    carry someone else's cookie, so there is nothing to forge; it goes through and is
    authenticated as usual.

The Mini App is served from WEBAPP_URL, inside Telegram's web view or Telegram Web's
iframe, so its requests carry that origin like the PWA's do.
"""

import json
import logging
from urllib.parse import urlsplit

from starlette.types import ASGIApp, Receive, Scope, Send

from app.config import settings
from app.i18n import language_for, t

log = logging.getLogger(__name__)

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# What Fetch Metadata calls a request the page made of its own origin, or one the user
# made directly (typing a URL, a bookmark).
SAFE_FETCH_SITES = {"same-origin", "none"}
DEFAULT_PORTS = {"http": 80, "https": 443}


def normalize_origin(value: str) -> str | None:
    """`scheme://host[:port]`, lower-case, default port dropped; None if not one."""
    try:
        parts = urlsplit(value.strip())
        port = parts.port
    except ValueError:
        return None
    if parts.scheme not in DEFAULT_PORTS or not parts.hostname:
        return None
    if parts.username or parts.password or parts.path not in ("", "/") or parts.query:
        return None
    host = parts.hostname.lower()
    if port is None or port == DEFAULT_PORTS[parts.scheme]:
        return f"{parts.scheme}://{host}"
    return f"{parts.scheme}://{host}:{port}"


def trusted_origins() -> set[str]:
    """Read on every request, so a changed setting needs no restart in tests."""
    candidates = [settings.webapp_url, *settings.trusted_origins.split(",")]
    return {origin for value in candidates if value.strip() and (origin := normalize_origin(value))}


def refusal(headers: dict[str, str]) -> str | None:
    """Why this state-changing request is refused, or None to let it through."""
    origin = headers.get("origin")
    if origin is not None:
        if normalize_origin(origin) in trusted_origins():
            return None
        return f"origin {origin!r} is not trusted"
    site = headers.get("sec-fetch-site")
    if site is not None and site not in SAFE_FETCH_SITES:
        return f"no origin, and sec-fetch-site is {site!r}"
    return None


class OriginCheck:
    """ASGI middleware: refuse cross-origin state changes before any handler runs."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in SAFE_METHODS:
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope["headers"]}
        reason = refusal(headers)
        if reason is None:
            await self.app(scope, receive, send)
            return

        log.warning("refused %s %s: %s", scope["method"], scope["path"], reason)
        language = language_for(headers.get("accept-language"), settings.default_language)
        detail = t("error.cross_origin", language)
        body = json.dumps({"detail": detail}, ensure_ascii=False).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
