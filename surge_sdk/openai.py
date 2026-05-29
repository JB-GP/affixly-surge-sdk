"""
surge_sdk.openai — Drop-in wrapper for the OpenAI Python SDK.

Replaces `import openai` with `from surge_sdk import openai`.
The wrapper intercepts chat.completions.create(), reads token counts
from response.usage, and reports to Surge in the background.
"""

import logging
from surge_sdk._reporter import report_usage, estimate_audio_cost
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


def _inject_include_usage(kwargs):
    """OpenAI streams don't include usage by default — the caller has to opt
    in via `stream_options.include_usage=True` for the final chunk to carry
    usage. We force it on (preserving any other stream_options) so the SDK
    can report. Callers iterating raw chunks will see one extra final
    chunk with usage populated.
    """
    so = dict(kwargs.get("stream_options") or {})
    so["include_usage"] = True
    kwargs["stream_options"] = so


def _absorb_openai_chunk(state, chunk):
    """Update model + usage state from an OpenAI ChatCompletionChunk."""
    try:
        mdl = getattr(chunk, 'model', None)
        if mdl:
            state['model'] = mdl
        usage = getattr(chunk, 'usage', None)
        if usage is not None:
            inp = getattr(usage, 'prompt_tokens', None)
            if inp is not None:
                state['input_tokens'] = inp
            out = getattr(usage, 'completion_tokens', None)
            if out is not None:
                state['output_tokens'] = out
    except Exception:
        pass


class _OpenAIStreamProxy:
    """Wraps an OpenAI Stream so usage from the final include_usage chunk
    is captured and reported when iteration completes (or the user exits
    the context manager). Other attributes are proxied through."""

    def __init__(self, real, surge_tags, requested_model):
        self._real = real
        self._surge_tags = surge_tags
        self._requested_model = requested_model
        self._state = {'model': 'unknown', 'input_tokens': 0, 'output_tokens': 0}
        self._iter = None
        self._reported = False

    def _report(self):
        if self._reported:
            return
        self._reported = True
        try:
            report_usage(
                "openai",
                self._state['model'],
                self._state['input_tokens'],
                self._state['output_tokens'],
                self._surge_tags,
                requested_model=self._requested_model,
            )
        except Exception as e:
            logger.debug("Failed to report streaming usage: %s", e)

    def __iter__(self):
        if self._iter is None:
            self._iter = iter(self._real)
        return self

    def __next__(self):
        if self._iter is None:
            self._iter = iter(self._real)
        try:
            chunk = next(self._iter)
        except StopIteration:
            self._report()
            raise
        _absorb_openai_chunk(self._state, chunk)
        return chunk

    def __enter__(self):
        entered = self._real.__enter__()
        if entered is not None and entered is not self._real:
            self._real = entered
            self._iter = None
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._report()
        return self._real.__exit__(exc_type, exc_val, exc_tb)

    def __getattr__(self, name):
        return getattr(self._real, name)


class _AsyncOpenAIStreamProxy:
    """Async sibling of _OpenAIStreamProxy."""

    def __init__(self, real, surge_tags, requested_model):
        self._real = real
        self._surge_tags = surge_tags
        self._requested_model = requested_model
        self._state = {'model': 'unknown', 'input_tokens': 0, 'output_tokens': 0}
        self._aiter = None
        self._reported = False

    def _report(self):
        if self._reported:
            return
        self._reported = True
        try:
            report_usage(
                "openai",
                self._state['model'],
                self._state['input_tokens'],
                self._state['output_tokens'],
                self._surge_tags,
                requested_model=self._requested_model,
            )
        except Exception as e:
            logger.debug("Failed to report streaming usage: %s", e)

    def __aiter__(self):
        if self._aiter is None:
            self._aiter = self._real.__aiter__()
        return self

    async def __anext__(self):
        if self._aiter is None:
            self._aiter = self._real.__aiter__()
        try:
            chunk = await self._aiter.__anext__()
        except StopAsyncIteration:
            self._report()
            raise
        _absorb_openai_chunk(self._state, chunk)
        return chunk

    async def __aenter__(self):
        entered = await self._real.__aenter__()
        if entered is not None and entered is not self._real:
            self._real = entered
            self._aiter = None
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._report()
        return await self._real.__aexit__(exc_type, exc_val, exc_tb)

    def __getattr__(self, name):
        return getattr(self._real, name)


class _SurgeCompletions:
    def __init__(self, real_completions):
        self._real = real_completions

    def create(self, **kwargs):
        surge_tags = kwargs.pop("surge_tags", None)
        overridden_from = _apply_override(kwargs)

        if kwargs.get("stream"):
            _inject_include_usage(kwargs)
            real_stream = self._real.create(**kwargs)
            return _OpenAIStreamProxy(real_stream, surge_tags, overridden_from)

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

        if kwargs.get("stream"):
            _inject_include_usage(kwargs)
            real_stream = await self._real.create(**kwargs)
            return _AsyncOpenAIStreamProxy(real_stream, surge_tags, overridden_from)

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


def _report_transcription(response, model, tags):
    """Report a transcription/translation call. Whisper bills per audio-minute,
    not tokens — cost comes from `response.duration` (seconds), which the OpenAI
    API only returns when the caller sets response_format="verbose_json". When
    duration is absent we still report the request with cost 0 so the call is
    visible (just without a cost estimate).
    """
    try:
        duration = getattr(response, 'duration', None)
        seconds = duration if isinstance(duration, (int, float)) else 0.0
        cost = estimate_audio_cost("openai", model or "unknown", seconds)
        report_usage("openai", model or "unknown", 0, 0, tags, cost_usd=cost)
    except Exception as e:
        logger.debug("Failed to report transcription usage: %s", e)


class _SurgeTranscriptions:
    def __init__(self, real):
        self._real = real

    def create(self, **kwargs):
        surge_tags = kwargs.pop("surge_tags", None)
        model = kwargs.get("model", "unknown")
        response = self._real.create(**kwargs)
        _report_transcription(response, model, surge_tags)
        return response

    def __getattr__(self, name):
        return getattr(self._real, name)


class _AsyncSurgeTranscriptions:
    def __init__(self, real):
        self._real = real

    async def create(self, **kwargs):
        surge_tags = kwargs.pop("surge_tags", None)
        model = kwargs.get("model", "unknown")
        response = await self._real.create(**kwargs)
        _report_transcription(response, model, surge_tags)
        return response

    def __getattr__(self, name):
        return getattr(self._real, name)


class _SurgeAudio:
    def __init__(self, real):
        self._real = real

    @property
    def transcriptions(self):
        return _SurgeTranscriptions(self._real.transcriptions)

    def __getattr__(self, name):
        return getattr(self._real, name)


class _AsyncSurgeAudio:
    def __init__(self, real):
        self._real = real

    @property
    def transcriptions(self):
        return _AsyncSurgeTranscriptions(self._real.transcriptions)

    def __getattr__(self, name):
        return getattr(self._real, name)


class OpenAI(_RealOpenAI):
    @property
    def chat(self):
        if not hasattr(self, '_surge_chat'):
            self._surge_chat = _SurgeChat(super().chat)
        return self._surge_chat

    @property
    def audio(self):
        if not hasattr(self, '_surge_audio'):
            self._surge_audio = _SurgeAudio(super().audio)
        return self._surge_audio


class AsyncOpenAI(_RealAsyncOpenAI):
    @property
    def chat(self):
        if not hasattr(self, '_surge_async_chat'):
            self._surge_async_chat = _AsyncSurgeChat(super().chat)
        return self._surge_async_chat

    @property
    def audio(self):
        if not hasattr(self, '_surge_async_audio'):
            self._surge_async_audio = _AsyncSurgeAudio(super().audio)
        return self._surge_async_audio
