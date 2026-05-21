"""
surge_sdk.gemini — Drop-in wrapper for the Google GenAI Python SDK.

Replaces `from google import genai` with `from surge_sdk import gemini as genai`.
The wrapper intercepts generate_content(), reads token counts from
response.usage_metadata, and reports to Surge in the background.
"""

import logging
from google import genai as _real_genai
from surge_sdk._reporter import report_usage
from surge_sdk._resolve import resolve_model

# H6 fix: explicit imports instead of wildcard
from google.genai import Client as _RealClient

logger = logging.getLogger("surge_sdk")

__all__ = ["Client", "configure"]


def _normalize_model(value):
    if isinstance(value, str) and value.startswith('models/'):
        return value[len('models/'):]
    return value or 'gemini-unknown'


def _extract_and_report(response, tags=None, requested_model=None):
    try:
        meta = getattr(response, 'usage_metadata', None)
        if not meta:
            return
        model = _normalize_model(getattr(response, 'model', None))
        inp = getattr(meta, 'prompt_token_count', 0) or 0
        out = getattr(meta, 'candidates_token_count', 0) or 0
        report_usage("gemini", model, inp, out, tags, requested_model=requested_model)
    except Exception as e:
        logger.debug("Failed to extract usage from Gemini response: %s", e)


def _apply_override(kwargs):
    surge_model = kwargs.pop("surge_model", None)
    requested = kwargs.get("model", "unknown")
    actual, overridden_from = resolve_model(requested, surge_model)
    if actual != requested:
        kwargs["model"] = actual
    return overridden_from


def _absorb_gemini_response(state, response):
    """Update state from a single Gemini streaming response. The final
    response in the iterator carries the cumulative usage_metadata."""
    try:
        mdl = getattr(response, 'model', None)
        if mdl:
            state['model'] = _normalize_model(mdl)
        meta = getattr(response, 'usage_metadata', None)
        if meta is not None:
            inp = getattr(meta, 'prompt_token_count', None)
            if inp is not None:
                state['input_tokens'] = inp
            out = getattr(meta, 'candidates_token_count', None)
            if out is not None:
                state['output_tokens'] = out
    except Exception:
        pass


class _GeminiStreamProxy:
    """Wrap a Gemini streaming response iterator. Report usage from the
    last chunk's usage_metadata when iteration ends. Gemini streams are
    sync-only in the current SDK wrapping; async aio support is not wired
    upstream of this proxy."""

    def __init__(self, real, surge_tags, requested_model, fallback_model):
        self._real = real
        self._surge_tags = surge_tags
        self._requested_model = requested_model
        self._state = {
            'model': fallback_model or 'gemini-unknown',
            'input_tokens': 0,
            'output_tokens': 0,
        }
        self._iter = None
        self._reported = False

    def _report(self):
        if self._reported:
            return
        self._reported = True
        try:
            report_usage(
                "gemini",
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
        _absorb_gemini_response(self._state, chunk)
        return chunk

    def __getattr__(self, name):
        return getattr(self._real, name)


class _SurgeModels:
    def __init__(self, real_models):
        self._real = real_models

    def generate_content(self, **kwargs):
        surge_tags = kwargs.pop("surge_tags", None)
        overridden_from = _apply_override(kwargs)
        response = self._real.generate_content(**kwargs)
        _extract_and_report(response, surge_tags, requested_model=overridden_from)
        return response

    def generate_content_stream(self, **kwargs):
        surge_tags = kwargs.pop("surge_tags", None)
        overridden_from = _apply_override(kwargs)
        # Capture the resolved model as a fallback in case no chunk carries
        # it back (responses sometimes omit `.model` on stream chunks).
        fallback_model = _normalize_model(kwargs.get("model"))
        real_iter = self._real.generate_content_stream(**kwargs)
        return _GeminiStreamProxy(real_iter, surge_tags, overridden_from, fallback_model)

    def __getattr__(self, name):
        return getattr(self._real, name)


class Client(_RealClient):
    @property
    def models(self):
        if not hasattr(self, '_surge_models'):
            self._surge_models = _SurgeModels(super().models)
        return self._surge_models


def configure(**kwargs):
    """Pass-through to google.genai.configure()."""
    return _real_genai.configure(**kwargs)
