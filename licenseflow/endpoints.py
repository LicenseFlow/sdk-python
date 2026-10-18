"""Canonical REST paths (SDK v2.3+).

The api.licenseflow.dev gateway serves both these and the legacy
/functions/v1/<name> paths indefinitely.
"""
from urllib.parse import urlsplit

import requests

CANONICAL_ENDPOINTS = {
    "verify-license": "/v1/licenses/verify",
    "activate-license": "/v1/licenses/activate",
    "deactivate-license": "/v1/licenses/deactivate",
    "checkout-license": "/v1/licenses/checkout",
    "lease-status": "/v1/licenses/lease-status",
    "generate-offline-license": "/v1/licenses/offline",
    "record-usage": "/v1/usage/record",
    "resolve-entitlements": "/v1/entitlements/resolve",
    "check-entitlement": "/v1/entitlements/check",
    "authorize": "/v1/access/authorize",
    "mcp-gateway": "/v1/mcp-gateway",
}

GATEWAY_HOST = "api.licenseflow.dev"
_LEGACY_PREFIX = "/functions/v1/"


def canonical_url(url):
    """Return the canonical URL for a legacy gateway URL, or None."""
    parts = urlsplit(url)
    if parts.hostname != GATEWAY_HOST:
        return None
    path = parts.path
    idx = path.find(_LEGACY_PREFIX)
    if idx < 0:
        return None
    name = path[idx + len(_LEGACY_PREFIX):]
    target = CANONICAL_ENDPOINTS.get(name)
    if not target:
        return None
    query = f"?{parts.query}" if parts.query else ""
    return f"{parts.scheme}://{parts.netloc}{target}{query}"


class CanonicalSession(requests.Session):
    """Session that sends core calls to canonical paths, falling back once
    to the legacy path if the gateway itself does not recognise them."""

    def request(self, method, url, *args, **kwargs):
        canonical = canonical_url(url)
        if canonical:
            response = super().request(method, canonical, *args, **kwargs)
            if response.status_code != 404 or response.headers.get("X-LicenseFlow-Route"):
                return response
        return super().request(method, url, *args, **kwargs)
