"""
surge_sdk.openai — Drop-in wrapper for the OpenAI Python SDK.

Replaces `import openai` with `from surge_sdk import openai`.
The wrapper intercepts chat.completions.create(), reads token counts
from response.usage, and reports to Surge in the background.
"""

import logging
from surge_sdk._reporter import report_usage
from surge_sdk._resolve import resolve_model

# H6 fix: explicit imports instead of wildcard
from openai import OpenAI as _RealOpenAI, AsyncOpenAI as _RealAsyncOpenAI
from openai import (
    APIError, AuthenticationError, BadRequestError, NotFoundError,
    RateLimitError, APIConnectionError, APITimeoutError,
)

logger = logging.getLogger("surge_sdk")

__all__ = [
    "OpenAI", "AsyncOpenAI",
    "APIError", "AuthenticationError", "BadRequestError", "NotFoundError",
    "RateLimitError", "APIConnectionError", "APITimeoutError",
]


def _extract_and_report(response, tags=None, requested_model=None):
    try:
        model = getattr(response, 'model', 'unknown') or 'unknown'
        usage = getattr(response, 'usage', None)
        if usage:
            inp = getattr(usage, 'prompt_tokens', 0) or 0
            out = getattr(usage, 'completion_tokens', 0) or 0
            report_usage("openai", model, inp, out, tags, requested_model=requested_model)
    except Exception as e:
        logger.debug("Failed to extract usage from OpenAI response: %s", e)


def _apply_override(kwargs):
    surge_model = kwargs.pop("surge_model", None)
    requested = kwargs.get("model", "unknown")
    actual, overridden_from = resolve_model(requested, surge_model)
    if actual != requested:
        kwargs["model"] = actual
    return overridden_from


class _SurgeCompletions:
    def __init__(self, real_completions):
        self._real = real_completions

    def create(self, **kwargs):
        surge_tags = kwargs.pop("surge_tags", None)
        overridden_from = _apply_override(kwargs)
        response = self._real.create(**kwargs)
        _extract_and_report(response, surge_tags, requested_model=overridden_from)
        return response

    def __getattr__(self, name):
        return getattr(self._real, name)


class _AsyncSurgeCompletions:
    def __init__(self, real_completions):
        self._real = real_completions

    async def create(self, **kwargs):
        surge_tags = kwargs.pop("surge_tags", None)
        overridden_from = _apply_override(kwargs)
        response = await self._real.create(**kwargs)
        _extract_and_report(response, surge_tags, requested_model=overridden_from)
        return response

    def __getattr__(self, name):
        return getattr(self._real, name)


class _SurgeChat:
    def __init__(self, real_chat):
        self._real = real_chat

    @property
    def completions(self):
        return _SurgeCompletions(self._real.completions)

    def __getattr__(self, name):
        return getattr(self._real, name)


class _AsyncSurgeChat:
    def __init__(self, real_chat):
        self._real = real_chat

    @property
    def completions(self):
        return _AsyncSurgeCompletions(self._real.completions)

    def __getattr__(self, name):
        return getattr(self._real, name)


class OpenAI(_RealOpenAI):
    @property
    def chat(self):
        if not hasattr(self, '_surge_chat'):
            self._surge_chat = _SurgeChat(super().chat)
        return self._surge_chat


class AsyncOpenAI(_RealAsyncOpenAI):
    @property
    def chat(self):
        if not hasattr(self, '_surge_async_chat'):
            self._surge_async_chat = _AsyncSurgeChat(super().chat)
        return self._surge_async_chat
