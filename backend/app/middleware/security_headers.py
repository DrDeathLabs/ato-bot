"""Security headers middleware for browser-facing responses."""

from typing import Callable

from fastapi import Request, Response

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "base-uri 'self'; "
    "frame-ancestors 'none'; "
    "object-src 'none'; "
    "form-action 'self'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "manifest-src 'self';"
)


def _directive_value(name: str) -> str:
    prefix = f"{name} "
    for part in CONTENT_SECURITY_POLICY.split(";"):
        item = part.strip()
        if item.startswith(prefix):
            return item[len(prefix):].strip()
    return ""


def csp_allows_inline_scripts() -> bool:
    return "'unsafe-inline'" in _directive_value("script-src")


def csp_allows_inline_styles() -> bool:
    return "'unsafe-inline'" in _directive_value("style-src")


async def security_headers_middleware(request: Request, call_next: Callable) -> Response:
    response = await call_next(request)
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
    if "server" in response.headers:
        del response.headers["server"]
    return response
