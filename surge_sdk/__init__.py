"""
surge-sdk — Lightweight cost-attribution wrapper for AI provider SDKs.

Usage:
    # Instead of:
    #   import anthropic
    # Use:
    from surge_sdk import anthropic

    # Configure tags once:
    from surge_sdk import configure
    configure(
        product_line="flow",
        default_tags={"team": "engineering"},
    )

    # Then use the client as normal — tags are injected automatically:
    client = anthropic.Anthropic(api_key="sk-...")
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": "Hello"}],
        # Optional per-request tags:
        metadata={"customer_id": "cust_123", "feature": "chat"},
    )

    # Track arbitrary product events (not tied to an AI call):
    from surge_sdk import track
    track(
        event="parse.repo.connected",
        tenant="github_username_or_user_id",
        properties={"repo": "owner/repo", "language": "python"},
    )
"""

from surge_sdk._config import configure, get_config
from surge_sdk._reporter import (
    track, track_quota_event, flush, set_diagnostics, SurgeReportError,
)

# Single source of truth for the version is pyproject.toml; at runtime we read
# it back from the installed package metadata (generated at build) so there is
# no second hard-coded copy to drift. The literal fallback only applies when
# running from an uninstalled source checkout, and is kept equal to pyproject.
try:
    from importlib.metadata import version as _pkg_version, PackageNotFoundError
    __version__ = _pkg_version("affixly-surge-sdk")
except Exception:  # PackageNotFoundError, or importlib.metadata missing
    __version__ = "0.7.0"

__all__ = [
    "configure",
    "get_config",
    "track",
    "track_quota_event",
    "flush",
    "set_diagnostics",
    "SurgeReportError",
    "__version__",
]
