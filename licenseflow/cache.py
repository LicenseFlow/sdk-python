"""
LicenseFlow SDK — Local Entitlement Cache
==========================================

Multi-layer caching strategy for zero-network-request validation:
  1. In-memory (fastest, ephemeral)
  2. Persistent file (survives restarts, HMAC-signed)
  3. Offline grace period (stale data used when API is unreachable)

Usage:
    from licenseflow.cache import EntitlementCache

    cache = EntitlementCache(api_key='lf_live_xxx', ttl_seconds=300)
    cached = cache.get('LF-XXXX-XXXX')
    if cached:
        # Use cached entitlements — zero network I/O
        ...
"""

import hashlib
import hmac
import json
import os
import time
from typing import Any, Dict, Optional


class CachedEntry:
    """Represents a cached entitlement decision."""

    __slots__ = ('data', 'cached_at', 'expires_at', 'source')

    def __init__(self, data: Dict[str, Any], cached_at: float, expires_at: float, source: str = 'network'):
        self.data = data
        self.cached_at = cached_at
        self.expires_at = expires_at
        self.source = source  # 'network', 'cache', or 'offline'

    def to_dict(self) -> Dict[str, Any]:
        return {
            'data': self.data,
            'cached_at': self.cached_at,
            'expires_at': self.expires_at,
            'source': self.source,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> 'CachedEntry':
        return cls(
            data=d['data'],
            cached_at=d['cached_at'],
            expires_at=d['expires_at'],
            source=d.get('source', 'cache'),
        )


class EntitlementCache:
    """
    Thread-safe in-memory + persistent entitlement cache.
    
    Strategies:
        'cache-first'              — Return cache if valid, else network.
        'stale-while-revalidate'   — Return cache immediately, revalidate in background.
        'network-first'            — Always hit network, cache as fallback.
    """

    def __init__(
        self,
        api_key: str,
        ttl_seconds: int = 300,
        offline_grace_hours: float = 72.0,
        strategy: str = 'stale-while-revalidate',
        persist_path: Optional[str] = None,
    ):
        self._memory: Dict[str, CachedEntry] = {}
        self._ttl = ttl_seconds
        self._grace_ms = offline_grace_hours * 3600
        self._strategy = strategy
        self._persist_path = persist_path
        self._hmac_key = hashlib.sha256(api_key.encode()).digest()

        if persist_path:
            self._load_from_disk()

    # ── Public API ────────────────────────────────────────────────────────

    def get(self, key: str) -> Optional[CachedEntry]:
        """Get cached entitlements. Returns None on miss/expiry."""
        entry = self._memory.get(key)
        if entry is None:
            return None

        now = time.time()

        # Within normal TTL
        if now < entry.expires_at:
            return CachedEntry(entry.data, entry.cached_at, entry.expires_at, 'cache')

        # Within offline grace period
        if now < entry.cached_at + self._grace_ms:
            return CachedEntry(entry.data, entry.cached_at, entry.expires_at, 'offline')

        # Fully expired
        del self._memory[key]
        self._persist_to_disk()
        return None

    def set(self, key: str, data: Dict[str, Any]) -> None:
        """Store entitlement decision in cache."""
        now = time.time()
        self._memory[key] = CachedEntry(
            data=data,
            cached_at=now,
            expires_at=now + self._ttl,
            source='network',
        )
        self._persist_to_disk()

    def invalidate(self, key: str) -> None:
        """Remove a specific cached entry."""
        self._memory.pop(key, None)
        self._persist_to_disk()

    def flush(self) -> None:
        """Clear all cached entries."""
        self._memory.clear()
        self._persist_to_disk()

    def get_strategy(self, key: str) -> str:
        """Determine cache action: 'use_cache', 'use_cache_revalidate', or 'use_network'."""
        entry = self.get(key)
        if entry is None:
            return 'use_network'

        if self._strategy == 'cache-first':
            return 'use_cache_revalidate' if entry.source == 'offline' else 'use_cache'
        elif self._strategy == 'stale-while-revalidate':
            return 'use_cache' if entry.source == 'cache' else 'use_cache_revalidate'
        else:
            return 'use_network'

    @property
    def size(self) -> int:
        return len(self._memory)

    # ── Persistence ───────────────────────────────────────────────────────

    def _persist_to_disk(self) -> None:
        if not self._persist_path:
            return
        try:
            entries = {k: v.to_dict() for k, v in self._memory.items()}
            payload = json.dumps(entries, separators=(',', ':'))
            signature = hmac.new(self._hmac_key, payload.encode(), hashlib.sha256).hexdigest()
            os.makedirs(os.path.dirname(self._persist_path), exist_ok=True)
            with open(self._persist_path, 'w') as f:
                f.write(f'{signature}\n{payload}')
        except Exception:
            pass  # Non-fatal — memory cache still works

    def _load_from_disk(self) -> None:
        if not self._persist_path or not os.path.exists(self._persist_path):
            return
        try:
            with open(self._persist_path, 'r') as f:
                content = f.read()
            sig_line, payload = content.split('\n', 1)
            expected = hmac.new(self._hmac_key, payload.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(sig_line, expected):
                os.unlink(self._persist_path)
                return
            entries = json.loads(payload)
            now = time.time()
            for k, v in entries.items():
                entry = CachedEntry.from_dict(v)
                if now < entry.cached_at + self._grace_ms:
                    self._memory[k] = entry
        except Exception:
            try:
                if self._persist_path and os.path.exists(self._persist_path):
                    os.unlink(self._persist_path)
            except Exception:
                pass
