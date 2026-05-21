"""
_reporter.py — Direct event reporting from the SDK to the Surge backend.

Uses a shared ThreadPoolExecutor (max 4 workers) with an atexit handler
for graceful shutdown. Redirects are disabled on HTTP requests to prevent
Bearer token leakage. Failures are logged (not swallowed silently).
"""

import atexit
import logging
import ssl
import warnings
from concurrent.futures import ThreadPoolExecutor
from surge_sdk._config import get_config

logger = logging.getLogger("surge_sdk")

_MAX_TAG_LENGTH = 256
_MAX_WORKERS = 4
_REQUEST_TIMEOUT = 5
_pool = ThreadPoolExecutor(max_workers=_MAX_WORKERS, thread_name_prefix="surge-sdk")


# C5 fix: graceful shutdown on interpreter exit
def _shutdown_pool():
    try:
        _pool.shutdown(wait=True, cancel_futures=False)
    except Exception:
        pass

atexit.register(_shutdown_pool)


# C4 fix: disable HTTP redirects to prevent Bearer token leakage
import urllib.request

class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(
            req.full_url, code,
            f"Redirect to {newurl} blocked — Surge SDK does not follow redirects",
            headers, fp
        )

# OpenerDirector.open() does not accept a `context` kwarg — the SSL context
# must be attached to an HTTPSHandler at build time. build_opener uses a
# default-context HTTPSHandler if we don't supply one, which already verifies
# certs; this is mostly for clarity.
_opener = urllib.request.build_opener(
    urllib.request.HTTPSHandler(context=ssl.create_default_context()),
    _NoRedirectHandler,
)


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
    if len(s) > max_len:
        logger.warning("Tag value truncated from %d to %d chars", len(s), max_len)
        return s[:max_len]
    return s


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
    requested_model=None,
):
    """Submit a usage event to Surge's /api/events endpoint.

    Runs on a shared thread pool (4 workers) so the caller's code path
    is never blocked. Failures are logged, not swallowed silently.

    `requested_model` is the original model name passed by the caller
    when a model override changed it. Omitted from the payload when
    no override occurred.
    """
    cfg = get_config()
    if not cfg.surge_api_url:
        return

    import math
    cost = estimate_cost(provider, model, input_tokens, output_tokens)
    if not math.isfinite(cost):
        logger.warning("Cost estimate is not finite (model=%s), skipping report", model)
        return

    merged_tags = {**cfg.default_tags_dict, **(tags or {})}

    payload = {
        "provider": _truncate(provider),
        "model": _truncate(model),
        "input_tokens": int(input_tokens or 0),
        "output_tokens": int(output_tokens or 0),
        "cost_usd": round(cost, 6),
        "requests": 1,
        "product_line": _truncate(cfg.product_line),
        "feature": _truncate(merged_tags.get("feature")),
        "customer_id": _truncate(merged_tags.get("customer_id")),
    }

    if requested_model:
        requested_cost = estimate_cost(provider, requested_model, input_tokens, output_tokens)
        if math.isfinite(requested_cost):
            payload["requested_model"] = _truncate(requested_model)
            payload["requested_cost_usd"] = round(requested_cost, 6)

    def _send():
        try:
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
            # C4: use _opener (no redirects) instead of urlopen.
            # SSL context is attached to the HTTPSHandler at opener build time.
            _opener.open(req, timeout=_REQUEST_TIMEOUT)
        except Exception as e:
            # H8 fix: log instead of silently swallowing
            logger.debug("Surge event report failed: %s", e)

    try:
        _pool.submit(_send)
    except RuntimeError:
        # Pool has been shut down (interpreter exiting) — drop silently
        pass
