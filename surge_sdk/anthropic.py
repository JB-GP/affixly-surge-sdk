"""
surge_sdk.anthropic — Drop-in wrapper for the Anthropic Python SDK.

Replaces `import anthropic` with `from surge_sdk import anthropic`.
The wrapper injects Surge metadata tags into every messages.create()
call via Anthropic's `metadata` parameter, which flows through to
the Anthropic usage API and back to Surge for cost attribution.

What gets injected:
  metadata.user_id → "{product_line}:{customer_id}" or "{product_line}"
    Anthropic's metadata.user_id is the only field that appears in
    their usage export. We encode Surge's attribution tags into it
    as a structured string so they round-trip through billing data.

Everything else (api_key, model, max_tokens, streaming, tool_use, etc.)
passes through unchanged. The wrapper is transparent — if you remove
surge_sdk, switching back to `import anthropic` works with zero changes.
"""

import anthropic as _real_anthropic
from surge_sdk._config import get_config

# Re-export everything from the real SDK so `from surge_sdk.anthropic import X` works
from anthropic import *  # noqa: F401,F403
from anthropic import Anthropic as _RealAnthropic, AsyncAnthropic as _RealAsyncAnthropic


def _build_surge_user_id(per_request_metadata: dict | None = None) -> str | None:
    """Build the metadata.user_id string that encodes Surge tags.

    Format: "surge:{product_line}:{feature}:{customer_id}"
    Missing segments are omitted. The "surge:" prefix lets Surge's
    ingestion pipeline identify tagged vs untagged requests.
    """
    cfg = get_config()
    tags = {**cfg.default_tags}
    if per_request_metadata:
        tags.update(per_request_metadata)

    parts = ["surge"]
    parts.append(cfg.product_line or "_")
    parts.append(tags.get("feature", "_"))
    parts.append(tags.get("customer_id", "_"))

    # Only inject if at least one real tag is present
    if cfg.product_line or tags.get("feature") or tags.get("customer_id"):
        return ":".join(parts)
    return None


class _SurgeMessages:
    """Wraps client.messages to inject tags on create()."""

    def __init__(self, real_messages):
        self._real = real_messages

    def create(self, **kwargs):
        surge_metadata = kwargs.pop("surge_tags", None)
        metadata = kwargs.get("metadata", {}) or {}

        user_id = _build_surge_user_id(surge_metadata)
        if user_id:
            metadata["user_id"] = user_id
            kwargs["metadata"] = metadata

        return self._real.create(**kwargs)

    def stream(self, **kwargs):
        surge_metadata = kwargs.pop("surge_tags", None)
        metadata = kwargs.get("metadata", {}) or {}

        user_id = _build_surge_user_id(surge_metadata)
        if user_id:
            metadata["user_id"] = user_id
            kwargs["metadata"] = metadata

        return self._real.stream(**kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


class _AsyncSurgeMessages:
    """Async variant of _SurgeMessages."""

    def __init__(self, real_messages):
        self._real = real_messages

    async def create(self, **kwargs):
        surge_metadata = kwargs.pop("surge_tags", None)
        metadata = kwargs.get("metadata", {}) or {}

        user_id = _build_surge_user_id(surge_metadata)
        if user_id:
            metadata["user_id"] = user_id
            kwargs["metadata"] = metadata

        return await self._real.create(**kwargs)

    async def stream(self, **kwargs):
        surge_metadata = kwargs.pop("surge_tags", None)
        metadata = kwargs.get("metadata", {}) or {}

        user_id = _build_surge_user_id(surge_metadata)
        if user_id:
            metadata["user_id"] = user_id
            kwargs["metadata"] = metadata

        return await self._real.stream(**kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


class Anthropic(_RealAnthropic):
    """Drop-in replacement for anthropic.Anthropic with Surge tag injection."""

    @property
    def messages(self):
        return _SurgeMessages(super().messages)


class AsyncAnthropic(_RealAsyncAnthropic):
    """Drop-in replacement for anthropic.AsyncAnthropic with Surge tag injection."""

    @property
    def messages(self):
        return _AsyncSurgeMessages(super().messages)
