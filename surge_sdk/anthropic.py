"""
surge_sdk.anthropic — Drop-in wrapper for the Anthropic Python SDK.

Replaces `import anthropic` with `from surge_sdk import anthropic`.
The wrapper does two things:
  1. Injects Surge tags into metadata.user_id (for future provider-side attribution)
  2. Reports usage directly to Surge's /api/events after each call (real-time attribution)

Everything else passes through unchanged. The wrapper is transparent.
"""

import anthropic as _real_anthropic
from surge_sdk._config import get_config
from surge_sdk._reporter import report_usage

# Re-export everything from the real SDK
from anthropic import *  # noqa: F401,F403
from anthropic import Anthropic as _RealAnthropic, AsyncAnthropic as _RealAsyncAnthropic


def _build_surge_user_id(per_request_tags=None):
    cfg = get_config()
    tags = {**cfg.default_tags, **(per_request_tags or {})}
    parts = ["surge"]
    parts.append(cfg.product_line or "_")
    parts.append(tags.get("feature", "_"))
    parts.append(tags.get("customer_id", "_"))
    if cfg.product_line or tags.get("feature") or tags.get("customer_id"):
        return ":".join(parts)
    return None


def _extract_and_report(response, tags: dict | None):
    """Extract token counts from an Anthropic response and report to Surge."""
    try:
        model = getattr(response, 'model', 'unknown')
        usage = getattr(response, 'usage', None)
        if usage:
            inp = getattr(usage, 'input_tokens', 0)
            out = getattr(usage, 'output_tokens', 0)
            report_usage("anthropic", model, inp, out, tags)
    except Exception:
        pass  # Never crash the host app


class _SurgeMessages:
    def __init__(self, real_messages):
        self._real = real_messages

    def create(self, **kwargs):
        surge_tags = kwargs.pop("surge_tags", None)
        metadata = kwargs.get("metadata", {}) or {}
        user_id = _build_surge_user_id(surge_tags)
        if user_id:
            metadata["user_id"] = user_id
            kwargs["metadata"] = metadata

        response = self._real.create(**kwargs)
        _extract_and_report(response, surge_tags)
        return response

    def stream(self, **kwargs):
        surge_tags = kwargs.pop("surge_tags", None)
        metadata = kwargs.get("metadata", {}) or {}
        user_id = _build_surge_user_id(surge_tags)
        if user_id:
            metadata["user_id"] = user_id
            kwargs["metadata"] = metadata

        # For streaming, we can't easily get final token counts from the
        # stream manager itself — report what we can at stream creation.
        return self._real.stream(**kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


class _AsyncSurgeMessages:
    def __init__(self, real_messages):
        self._real = real_messages

    async def create(self, **kwargs):
        surge_tags = kwargs.pop("surge_tags", None)
        metadata = kwargs.get("metadata", {}) or {}
        user_id = _build_surge_user_id(surge_tags)
        if user_id:
            metadata["user_id"] = user_id
            kwargs["metadata"] = metadata

        response = await self._real.create(**kwargs)
        _extract_and_report(response, surge_tags)
        return response

    async def stream(self, **kwargs):
        surge_tags = kwargs.pop("surge_tags", None)
        metadata = kwargs.get("metadata", {}) or {}
        user_id = _build_surge_user_id(surge_tags)
        if user_id:
            metadata["user_id"] = user_id
            kwargs["metadata"] = metadata

        return await self._real.stream(**kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


class Anthropic(_RealAnthropic):
    @property
    def messages(self):
        return _SurgeMessages(super().messages)


class AsyncAnthropic(_RealAsyncAnthropic):
    @property
    def messages(self):
        return _AsyncSurgeMessages(super().messages)
