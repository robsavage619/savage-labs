from __future__ import annotations

import logging

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from shc.config import settings

log = logging.getLogger(__name__)

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class HostOriginMiddleware(BaseHTTPMiddleware):
    """Block requests from unexpected Host or Origin headers to prevent DNS rebinding."""

    async def dispatch(self, request: Request, call_next: object) -> Response:
        host = request.headers.get("host", "")
        expected_host = f"{settings.host}:{settings.port}"

        # Always allow loopback — the bind address (0.0.0.0 in prod) is irrelevant
        # to what clients put in the Host header.
        allowed_hosts = {
            f"127.0.0.1:{settings.port}",
            f"localhost:{settings.port}",
        }
        if settings.tailscale_host:
            allowed_hosts.add(settings.tailscale_host)
            allowed_hosts.add(f"{settings.tailscale_host}:{settings.port}")

        if host and host not in allowed_hosts:
            log.warning("rejected request with Host: %s", host)
            return Response("Forbidden", status_code=403)

        if request.method not in _SAFE_METHODS:
            origin = request.headers.get("origin", "")
            if origin:
                # Allow any localhost / 127.0.0.1 origin — the dev preview server
                # uses a random port, so port-exact matching would block it.
                # DNS-rebinding protection is satisfied by requiring localhost/127.0.0.1.
                from urllib.parse import urlparse
                parsed = urlparse(origin)
                if parsed.hostname not in ("localhost", "127.0.0.1"):
                    log.warning("rejected request with Origin: %s", origin)
                    return Response("Forbidden", status_code=403)

        return await call_next(request)  # type: ignore[arg-type]
