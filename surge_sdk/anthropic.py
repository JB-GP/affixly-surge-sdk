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
)

# HUMAN_PROMPT / AI_PROMPT belonged to the legacy Text Completions API and were
# removed in anthropic 1.x, where importing them raised ImportError and broke
# `from surge_sdk import anthropic` entirely. Re-export them only when the
# installed anthropic still provides them (0.x), so both majors import cleanly.
try:
    from anthropic import HUMAN_PROMPT, AI_PROMPT  # noqa: F401
    _LEGACY_PROMPTS = ["HUMAN_PROMPT", "AI_PROMPT"]
except ImportError:
    _LEGACY_PROMPTS = []

logger = logging.getLogger("surge_sdk")

__all__ = [
    "Anthropic", "AsyncAnthropic",
    "APIError", "AuthenticationError", "BadRequestError", "NotFoundError",
    "RateLimitError", "APIConnectionError", "APITimeoutError",
] + _LEGACY_PROMPTS


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


def _absorb_stream_event(state, event):
    """Mutate `state` with token/model info from an Anthropic stream event.

    Anthropic emits MessageStartEvent (input_tokens + initial model),
    MessageDeltaEvent (cumulative output_tokens), and others. We pluck
    usage out of whichever events expose it, so the same code path works
    for the lower-level `Stream` and the higher-level `MessageStream`.
    """
    try:
        msg = getattr(event, 'message', None)
        if msg is not None:
            mdl = getattr(msg, 'model', None)
            if mdl:
                state['model'] = mdl
            mu = getattr(msg, 'usage', None)
            if mu is not None:
                inp = getattr(mu, 'input_tokens', None)
                if inp:
                    state['input_tokens'] = inp
                out = getattr(mu, 'output_tokens', None)
                if out:
                    state['output_tokens'] = out
        eu = getattr(event, 'usage', None)
        if eu is not None:
            inp = getattr(eu, 'input_tokens', None)
            if inp:
                state['input_tokens'] = inp
            out = getattr(eu, 'output_tokens', None)
            if out is not None:
                state['output_tokens'] = out
    except Exception:
        # Reporting must never break the caller's iteration
        pass


def _state_incomplete(state):
    """True when the proxy never saw usage flow through its own iterator."""
    return state['model'] == 'unknown' or (
        not state['input_tokens'] and not state['output_tokens']
    )


def _fill_state_from_final(state, final):
    """Populate `state` from a fully-accumulated Message (model + usage).

    Fallback for callers that drain the stream via helpers like `text_stream`
    or `get_final_message()` instead of iterating events through the proxy —
    those bypass `_absorb_stream_event`, leaving state at its defaults. The
    final message carries the same totals, so we read them off it instead.
    """
    if final is None:
        return
    mdl = getattr(final, 'model', None)
    if mdl:
        state['model'] = mdl
    u = getattr(final, 'usage', None)
    if u is not None:
        inp = getattr(u, 'input_tokens', None)
        if inp:
            state['input_tokens'] = inp
        out = getattr(u, 'output_tokens', None)
        if out is not None:
            state['output_tokens'] = out


class _SurgeStreamProxy:
    """Wraps an Anthropic Stream/MessageStream. Reports usage exactly once
    when iteration completes or the context-manager exits (whichever first).
    Other attributes (close, text_stream, get_final_message, etc.) are
    proxied through unchanged so callers see the real stream API.
    """

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
        if _state_incomplete(self._state):
            try:
                _fill_state_from_final(self._state, self._real.get_final_message())
            except Exception as e:
                logger.debug("Streaming usage fallback (get_final_message) failed: %s", e)
        try:
            report_usage(
                "anthropic",
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
            event = next(self._iter)
        except StopIteration:
            self._report()
            raise
        _absorb_stream_event(self._state, event)
        return event

    def __enter__(self):
        entered = self._real.__enter__()
        # MessageStreamManager's __enter__ returns a MessageStream; rebind so
        # iteration and helper methods (.text_stream, .get_final_message)
        # all reach the underlying stream rather than the manager.
        if entered is not None and entered is not self._real:
            self._real = entered
            self._iter = None
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Report whatever we captured even if the user broke early.
        self._report()
        return self._real.__exit__(exc_type, exc_val, exc_tb)

    def __getattr__(self, name):
        return getattr(self._real, name)


class _AsyncSurgeStreamProxy:
    """Async sibling of _SurgeStreamProxy. Same semantics, async protocol."""

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
                "anthropic",
                self._state['model'],
                self._state['input_tokens'],
                self._state['output_tokens'],
                self._surge_tags,
                requested_model=self._requested_model,
            )
        except Exception as e:
            logger.debug("Failed to report streaming usage: %s", e)

    async def _report_async(self):
        if self._reported:
            return
        if _state_incomplete(self._state):
            try:
                _fill_state_from_final(self._state, await self._real.get_final_message())
            except Exception as e:
                logger.debug("Streaming usage fallback (get_final_message) failed: %s", e)
        self._report()

    def __aiter__(self):
        if self._aiter is None:
            self._aiter = self._real.__aiter__()
        return self

    async def __anext__(self):
        if self._aiter is None:
            self._aiter = self._real.__aiter__()
        try:
            event = await self._aiter.__anext__()
        except StopAsyncIteration:
            await self._report_async()
            raise
        _absorb_stream_event(self._state, event)
        return event

    async def __aenter__(self):
        entered = await self._real.__aenter__()
        if entered is not None and entered is not self._real:
            self._real = entered
            self._aiter = None
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._report_async()
        return await self._real.__aexit__(exc_type, exc_val, exc_tb)

    def __getattr__(self, name):
        return getattr(self._real, name)


def _inject_metadata_user_id(kwargs, surge_tags):
    """Mutate kwargs to inject Anthropic's metadata.user_id with our tag info."""
    metadata = dict(kwargs.get("metadata") or {})
    user_id = _build_surge_user_id(surge_tags)
    if user_id:
        metadata["user_id"] = user_id
        kwargs["metadata"] = metadata


class _SurgeMessages:
    def __init__(self, real_messages):
        self._real = real_messages

    def create(self, **kwargs):
        surge_tags = kwargs.pop("surge_tags", None)
        overridden_from = _apply_override(kwargs)
        _inject_metadata_user_id(kwargs, surge_tags)

        if kwargs.get("stream"):
            # Streaming variant of create(): returns a Stream object that's
            # both iterable and a context manager. Wrap so we capture usage
            # as events flow through.
            real_stream = self._real.create(**kwargs)
            return _SurgeStreamProxy(real_stream, surge_tags, overridden_from)

        response = self._real.create(**kwargs)
        _extract_and_report(response, surge_tags, requested_model=overridden_from)
        return response

    def stream(self, **kwargs):
        surge_tags = kwargs.pop("surge_tags", None)
        overridden_from = _apply_override(kwargs)
        _inject_metadata_user_id(kwargs, surge_tags)
        real_manager = self._real.stream(**kwargs)
        return _SurgeStreamProxy(real_manager, surge_tags, overridden_from)

    def __getattr__(self, name):
        return getattr(self._real, name)


class _AsyncSurgeMessages:
    def __init__(self, real_messages):
        self._real = real_messages

    async def create(self, **kwargs):
        surge_tags = kwargs.pop("surge_tags", None)
        overridden_from = _apply_override(kwargs)
        _inject_metadata_user_id(kwargs, surge_tags)

        if kwargs.get("stream"):
            real_stream = await self._real.create(**kwargs)
            return _AsyncSurgeStreamProxy(real_stream, surge_tags, overridden_from)

        response = await self._real.create(**kwargs)
        _extract_and_report(response, surge_tags, requested_model=overridden_from)
        return response

    def stream(self, **kwargs):
        # AsyncAnthropic.messages.stream() returns an AsyncMessageStreamManager
        # synchronously (no await — the awaitable bits happen on __aenter__).
        surge_tags = kwargs.pop("surge_tags", None)
        overridden_from = _apply_override(kwargs)
        _inject_metadata_user_id(kwargs, surge_tags)
        real_manager = self._real.stream(**kwargs)
        return _AsyncSurgeStreamProxy(real_manager, surge_tags, overridden_from)

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
