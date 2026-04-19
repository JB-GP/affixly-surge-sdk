"""
_reporter.py — Direct event reporting from the SDK to the Surge backend.

After every provider API call, the SDK extracts usage metadata from the
response (model, tokens) and POSTs it to Surge's /api/events endpoint.

Uses a shared thread pool (max 4 workers) instead of spawning one thread
per call. Events that arrive faster than the pool drains are queued.
Failures are silently swallowed — the SDK must never break the host app.
"""

import warnings
from concurrent.futures import ThreadPoolExecutor
from surge_sdk._config import get_config

_MAX_TAG_LENGTH = 256
_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="surge-sdk")

# Pricing tables for client-side cost estimation (per million tokens)
_PRICING = {
    "anthropic": {
        "claude-opus-4-0":     (15.0, 75.0),
        "claude-opus-4-6":     (15.0, 75.0),
        "claude-sonnet-4-0":   (3.0,  15.0),
        "claude-sonnet-4-6":   (3.0,  15.0),
        "claude-haiku-3-5":    (0.80, 4.0),
        "claude-haiku-4-5":    (0.80, 4.0),
        "claude-3-5-sonnet":   (3.0,  15.0),
        "claude-3-opus":       (15.0, 75.0),
        "claude-3-haiku":      (0.25, 1.25),
    },
    "openai": {
        "gpt-4o":           (2.50, 10.00),
        "gpt-4o-mini":      (0.15, 0.60),
        "gpt-4-turbo":      (10.00, 30.00),
        "gpt-3.5-turbo":    (0.50, 1.50),
        "o1":               (15.00, 60.00),
        "o1-mini":          (3.00, 12.00),
    },
    "gemini": {
        "gemini-2.5-pro":   (1.25, 10.00),
        "gemini-2.5-flash": (0.15, 0.60),
        "gemini-2.0-flash": (0.10, 0.40),
        "gemini-1.5-pro":   (1.25, 5.00),
        "gemini-1.5-flash": (0.075, 0.30),
    },
}
_DEFAULT_PRICING = (3.0, 15.0)


def _validate_url(url):
    """Warn if surge_api_url is not HTTPS (except localhost for dev)."""
    if not url:
        return
    lower = url.lower()
    if lower.startswith("https://"):
        return
    if lower.startswith("http://localhost") or lower.startswith("http://127.0.0.1"):
        return
    warnings.warn(
        f"surge_api_url is not HTTPS: {url!r}. "
        "Your SDK API key will be transmitted in plaintext. "
        "Use https:// in production.",
        stacklevel=3,
    )


def _truncate(value, max_len=_MAX_TAG_LENGTH):
    """Truncate a tag value to prevent oversized payloads."""
    if value is None:
        return None
    s = str(value)
    return s[:max_len] if len(s) > max_len else s


def estimate_cost(provider, model, input_tokens, output_tokens):
    provider_pricing = _PRICING.get(provider, {})
    rates = _DEFAULT_PRICING
    for key, r in provider_pricing.items():
        if key in model:
            rates = r
            break
    return (input_tokens / 1_000_000) * rates[0] + (output_tokens / 1_000_000) * rates[1]


def report_usage(
    provider,
    model,
    input_tokens,
    output_tokens,
    tags=None,
):
    """Submit a usage event to Surge's /api/events endpoint.

    Runs on a shared thread pool (4 workers) so the caller's code path
    is never blocked. Failures are silently swallowed.
    """
    cfg = get_config()
    if not cfg.surge_api_url:
        return

    cost = estimate_cost(provider, model, input_tokens, output_tokens)
    merged_tags = {**cfg.default_tags, **(tags or {})}

    payload = {
        "provider": _truncate(provider),
        "model": _truncate(model),
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "cost_usd": round(cost, 6),
        "requests": 1,
        "product_line": _truncate(cfg.product_line),
        "feature": _truncate(merged_tags.get("feature")),
        "customer_id": _truncate(merged_tags.get("customer_id")),
    }

    def _send():
        try:
            import urllib.request
            import json
            headers = {"Content-Type": "application/json"}
            if cfg.surge_api_key:
                headers["Authorization"] = f"Bearer {cfg.surge_api_key}"
            req = urllib.request.Request(
                f"{cfg.surge_api_url.rstrip('/')}/api/events",
                data=json.dumps(payload).encode(),
                headers=headers,
                method="POST",
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception:
            pass  # Never crash the host app

    try:
        _pool.submit(_send)
    except RuntimeError:
        # Pool has been shut down (interpreter exiting) — drop silently
        pass
