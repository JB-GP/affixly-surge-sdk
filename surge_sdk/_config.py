"""
Global configuration for surge-sdk tag injection.

H10 fix: all reads/writes go through a threading.Lock so concurrent
configure() and report_usage() calls don't tear the config.
"""

import threading
from dataclasses import dataclass
from typing import Optional

_lock = threading.Lock()


@dataclass(frozen=True)
class SurgeConfig:
    """Immutable config snapshot. A new instance is created on every
    configure() call so readers never see a partially-updated object."""
    product_line: Optional[str] = None
    default_tags: tuple = ()  # stored as tuple of (k, v) pairs for immutability
    surge_api_url: Optional[str] = None
    surge_api_key: Optional[str] = None

    @property
    def default_tags_dict(self) -> dict:
        return dict(self.default_tags)


# Module-level mutable reference — protected by _lock
_config = SurgeConfig()


def configure(
    product_line: Optional[str] = None,
    default_tags: Optional[dict] = None,
    surge_api_url: Optional[str] = None,
    surge_api_key: Optional[str] = None,
):
    """Set global tags injected into every provider API call.

    Thread-safe: creates a new frozen config snapshot atomically.
    Should be called once at app startup before any AI calls.
    """
    global _config
    with _lock:
        cur = _config
        new_tags = tuple((default_tags or {}).items()) if default_tags is not None else cur.default_tags
        _config = SurgeConfig(
            product_line=product_line if product_line is not None else cur.product_line,
            default_tags=new_tags,
            surge_api_url=surge_api_url if surge_api_url is not None else cur.surge_api_url,
            surge_api_key=surge_api_key if surge_api_key is not None else cur.surge_api_key,
        )

    # Validate HTTPS — import here to avoid circular import at module level
    if surge_api_url is not None:
        from surge_sdk._reporter import _validate_url
        _validate_url(surge_api_url)


def get_config() -> SurgeConfig:
    """Return the current config snapshot. Thread-safe (reads a single reference)."""
    return _config
