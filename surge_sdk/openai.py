"""
surge_sdk.openai — Drop-in wrapper for the OpenAI Python SDK.

Replaces `import openai` with `from surge_sdk import openai`.
The wrapper intercepts chat.completions.create(), reads token counts
from response.usage, and reports to Surge in the background.

Everything else passes through unchanged.
"""

import openai as _real_openai
from surge_sdk._config import get_config
from surge_sdk._reporter import report_usage

# Re-export everything from the real SDK
from openai import *  # noqa: F401,F403
from openai import OpenAI as _RealOpenAI, AsyncOpenAI as _RealAsyncOpenAI


def _extract_and_report(response, tags=None):
    """Extract token counts from an OpenAI response and report to Surge."""
    try:
        model = getattr(response, 'model', 'unknown') or 'unknown'
        usage = getattr(response, 'usage', None)
        if usage:
            inp = getattr(usage, 'prompt_tokens', 0) or 0
            out = getattr(usage, 'completion_tokens', 0) or 0
            report_usage("openai", model, inp, out, tags)
    except Exception:
        pass


class _SurgeCompletions:
    """Wraps client.chat.completions to inject Surge reporting on create()."""

    def __init__(self, real_completions):
        self._real = real_completions

    def create(self, **kwargs):
        surge_tags = kwargs.pop("surge_tags", None)
        response = self._real.create(**kwargs)
        _extract_and_report(response, surge_tags)
        return response

    def __getattr__(self, name):
        return getattr(self._real, name)


class _AsyncSurgeCompletions:
    def __init__(self, real_completions):
        self._real = real_completions

    async def create(self, **kwargs):
        surge_tags = kwargs.pop("surge_tags", None)
        response = await self._real.create(**kwargs)
        _extract_and_report(response, surge_tags)
        return response

    def __getattr__(self, name):
        return getattr(self._real, name)


class _SurgeChat:
    """Wraps client.chat to expose the completions wrapper."""

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
    """Drop-in replacement for openai.OpenAI with Surge reporting."""

    @property
    def chat(self):
        return _SurgeChat(super().chat)


class AsyncOpenAI(_RealAsyncOpenAI):
    """Drop-in replacement for openai.AsyncOpenAI with Surge reporting."""

    @property
    def chat(self):
        return _AsyncSurgeChat(super().chat)
