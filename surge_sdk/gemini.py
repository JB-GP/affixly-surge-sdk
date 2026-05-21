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


def _extract_and_report(response, tags=None, requested_model=None):
    try:
        meta = getattr(response, 'usage_metadata', None)
        if not meta:
            return
        model = getattr(response, 'model', None) or 'gemini-unknown'
        if isinstance(model, str) and model.startswith('models/'):
            model = model[7:]
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
        kwargs.pop("surge_tags", None)  # Remove so real SDK doesn't see it
        _apply_override(kwargs)  # Honor override even for stream
        return self._real.generate_content_stream(**kwargs)

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
