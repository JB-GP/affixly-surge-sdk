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
"""

from surge_sdk._config import configure, get_config

__version__ = "0.2.0"
__all__ = ["configure", "get_config"]
