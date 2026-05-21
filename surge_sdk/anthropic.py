"""
surge_sdk.anthropic — Drop-in wrapper for the Anthropic Python SDK.

Replaces `import anthropic` with `from surge_sdk import anthropic`.
The wrapper intercepts messages.create(), reads token counts from
response.usage, and reports to Surge in the background.
"""

import logging
from surge_sdk._config import get_config
from surge_sdk._reporter import report_usage
from surge_sdk._resolve import resolve_model

# H6 fix: explicit imports instead of wildcard — only re-export what users need
from anthropic import Anthropic as _RealAnthropic, AsyncAnthropic as _RealAsyncAnthropic
from anthropic import (
    APIError, AuthenticationError, BadRequestError, NotFoundError,
    RateLimitError, APIConnectionError, APITimeoutError,
    HUMAN_PROMPT, AI_PROMPT,
)

logger = logging.getLogger("surge_sdk")

__all__ = [
    "Anthropic", "AsyncAnthropic",
    "APIError", "AuthenticationError", "BadRequestError", "NotFoundError",
    "RateLimitError", "APIConnectionError", "APITimeoutError",
    "HUMAN_PROMPT", "AI_PROMPT",
]


def _build_surge_user_id(per_request_tags=None):
    cfg = get_config()
    tags = {**cfg.default_tags_dict, **(per_request_tags or {})}
    parts = ["surge"]
    parts.append(cfg.product_line or "_")
    parts.append(tags.get("feature", "_"))
    parts.append(tags.get("customer_id", "_"))
    if cfg.product_line or tags.get("feature") or tags.get("customer_id"):
        return ":".join(parts)
    return None


def _extract_and_report(response, tags=None, requested_model=None):
    try:
        model = getattr(response, 'model', 'unknown')
        usage = getattr(response, 'usage', None)
        if usage:
            inp = getattr(usage, 'input_tokens', 0) or 0
            out = getattr(usage, 'output_tokens', 0) or 0
            report_usage("anthropic", model, inp, out, tags, requested_model=requested_model)
    except Exception as e:
        logger.debug("Failed to extract usage from Anthropic response: %s", e)


def _apply_override(kwargs):
    """Pop surge_model, resolve override, mutate kwargs['model'] if changed.

    Returns the original-requested model when an override was applied,
    else None — passed through to the reporter as `requested_model`.
    """
    surge_model = kwargs.pop("surge_model", None)
    requested = kwargs.get("model", "unknown")
    actual, overridden_from = resolve_model(requested, surge_model)
    if actual != requested:
        kwargs["model"] = actual
    return overridden_from


class _SurgeMessages:
    def __init__(self, real_messages):
        self._real = real_messages

    def create(self, **kwargs):
        surge_tags = kwargs.pop("surge_tags", None)
        overridden_from = _apply_override(kwargs)
        # H11 fix: copy metadata dict before mutating
        metadata = dict(kwargs.get("metadata") or {})
        user_id = _build_surge_user_id(surge_tags)
        if user_id:
            metadata["user_id"] = user_id
            kwargs["metadata"] = metadata

        response = self._real.create(**kwargs)
        _extract_and_report(response, surge_tags, requested_model=overridden_from)
        return response

    def stream(self, **kwargs):
        surge_tags = kwargs.pop("surge_tags", None)
        _apply_override(kwargs)
        metadata = dict(kwargs.get("metadata") or {})
        user_id = _build_surge_user_id(surge_tags)
        if user_id:
            metadata["user_id"] = user_id
            kwargs["metadata"] = metadata
        return self._real.stream(**kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


class _AsyncSurgeMessages:
    def __init__(self, real_messages):
        self._real = real_messages

    async def create(self, **kwargs):
        surge_tags = kwargs.pop("surge_tags", None)
        overridden_from = _apply_override(kwargs)
        metadata = dict(kwargs.get("metadata") or {})
        user_id = _build_surge_user_id(surge_tags)
        if user_id:
            metadata["user_id"] = user_id
            kwargs["metadata"] = metadata

        response = await self._real.create(**kwargs)
        _extract_and_report(response, surge_tags, requested_model=overridden_from)
        return response

    async def stream(self, **kwargs):
        surge_tags = kwargs.pop("surge_tags", None)
        _apply_override(kwargs)
        metadata = dict(kwargs.get("metadata") or {})
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
        if not hasattr(self, '_surge_messages'):
            self._surge_messages = _SurgeMessages(super().messages)
        return self._surge_messages


class AsyncAnthropic(_RealAsyncAnthropic):
    @property
    def messages(self):
        if not hasattr(self, '_surge_async_messages'):
            self._surge_async_messages = _AsyncSurgeMessages(super().messages)
        return self._surge_async_messages
