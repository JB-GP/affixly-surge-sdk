"""
surge_sdk.gemini — Drop-in wrapper for the Google GenAI Python SDK.

Supports the newer google-genai Client pattern:
    # Before:
    from google import genai
    # After:
    from surge_sdk import gemini as genai

The wrapper intercepts generate_content() calls, reads token counts
from response.usage_metadata, and reports to Surge in the background.

Everything else passes through unchanged.
"""

from google import genai as _real_genai
from surge_sdk._reporter import report_usage

# Re-export everything from the real SDK
from google.genai import *  # noqa: F401,F403
from google.genai import Client as _RealClient


def _extract_and_report(response, tags=None):
    """Extract token counts from a Gemini response and report to Surge."""
    try:
        meta = getattr(response, 'usage_metadata', None)
        if not meta:
            return
        model = getattr(response, 'model', None) or 'gemini-unknown'
        # Normalize model name — response.model may include "models/" prefix
        if isinstance(model, str) and model.startswith('models/'):
            model = model[7:]
        inp = getattr(meta, 'prompt_token_count', 0) or 0
        out = getattr(meta, 'candidates_token_count', 0) or 0
        report_usage("gemini", model, inp, out, tags)
    except Exception:
        pass


class _SurgeModels:
    """Wraps client.models to inject Surge reporting on generate_content()."""

    def __init__(self, real_models):
        self._real = real_models

    def generate_content(self, **kwargs):
        surge_tags = kwargs.pop("surge_tags", None)
        response = self._real.generate_content(**kwargs)
        _extract_and_report(response, surge_tags)
        return response

    def generate_content_stream(self, **kwargs):
        surge_tags = kwargs.pop("surge_tags", None)
        # Streaming — can't easily get final token counts mid-stream
        return self._real.generate_content_stream(**kwargs)

    def __getattr__(self, name):
        return getattr(self._real, name)


class Client(_RealClient):
    """Drop-in replacement for google.genai.Client with Surge reporting."""

    @property
    def models(self):
        if not hasattr(self, '_surge_models'):
            self._surge_models = _SurgeModels(super().models)
        return self._surge_models


# Also expose the module-level helpers for the older pattern
def configure(**kwargs):
    """Pass-through to google.genai.configure()."""
    return _real_genai.configure(**kwargs)
