"""
Global configuration for surge-sdk tag injection.
"""

from dataclasses import dataclass, field
from typing import Optional

@dataclass
class SurgeConfig:
    product_line: Optional[str] = None
    default_tags: dict = field(default_factory=dict)
    # Optional: Surge API endpoint for direct event reporting (Phase 2+)
    surge_api_url: Optional[str] = None
    surge_api_key: Optional[str] = None

_config = SurgeConfig()


def configure(
    product_line: Optional[str] = None,
    default_tags: Optional[dict] = None,
    surge_api_url: Optional[str] = None,
    surge_api_key: Optional[str] = None,
):
    """Set global tags that get injected into every provider API call.

    Args:
        product_line: Top-level cost attribution bucket (e.g. "flow", "support-bot").
        default_tags: Dict of key-value pairs merged into every request's metadata.
        surge_api_url: Optional Surge backend URL for direct event reporting.
        surge_api_key: Optional Bearer token for Surge API.
    """
    global _config
    if product_line is not None:
        _config.product_line = product_line
    if default_tags is not None:
        _config.default_tags = default_tags
    if surge_api_url is not None:
        _config.surge_api_url = surge_api_url
    if surge_api_key is not None:
        _config.surge_api_key = surge_api_key


def get_config() -> SurgeConfig:
    return _config
