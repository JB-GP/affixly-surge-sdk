"""
_reporter.py — Direct event reporting from the SDK to the Surge backend.

Uses a shared ThreadPoolExecutor (max 4 workers) with an atexit handler
for graceful shutdown. Redirects are disabled on HTTP requests to prevent
Bearer token leakage. Failures are logged (not swallowed silently).
"""

import atexit
import logging
import ssl
import threading
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


# ── Reporting lifecycle & diagnostics ────────────────────────────────────────
# Track outstanding work so flush() can block until reports have actually been
# sent — useful in short-lived scripts and serverless, where the atexit drain
# may not run before the process freezes.
_inflight_lock = threading.Lock()
_inflight_futures = set()
_inflight_threads = set()

# Opt-in diagnostics. Surge never raises on a reporting failure; register a
# handler to observe dropped reports (e.g. bump a metric) without changing that.
_on_report_error = None

# Warn at most once per process when the backend signals the event quota is
# exceeded (X-Surge-Quota: exceeded). Delivery just stops counting server-side;
# we never raise.
_quota_warned = False
_quota_warn_lock = threading.Lock()


def set_diagnostics(on_report_error=None):
    """Opt in to reporting diagnostics without changing failure behavior.

    ``on_report_error(exc)`` is called best-effort whenever a usage/track report
    fails to send. Surge still never raises into your code. Pass ``None`` to
    clear the handler.
    """
    global _on_report_error
    _on_report_error = on_report_error


def _emit_report_error(exc):
    handler = _on_report_error
    if handler is None:
        return
    try:
        handler(exc)
    except Exception:
        logger.debug("surge_sdk on_report_error handler raised; ignored")


def _note_quota_exceeded():
    global _quota_warned
    with _quota_warn_lock:
        if _quota_warned:
            return
        _quota_warned = True
    warnings.warn(
        "Surge: event quota exceeded for this period — new events are being "
        "dropped server-side and won't appear on your dashboard. Reported once "
        "per process; never raises. Upgrade the plan to resume ingestion.",
        stacklevel=2,
    )


def _check_quota_header(response):
    """Inspect a report response for the X-Surge-Quota signal. Best-effort."""
    try:
        if response is not None and response.headers.get("X-Surge-Quota") == "exceeded":
            _note_quota_exceeded()
    except Exception:
        pass


def _discard_future(fut):
    with _inflight_lock:
        _inflight_futures.discard(fut)


def flush(timeout=None):
    """Block until outstanding usage/track reports have been sent, or ``timeout``
    seconds elapse. Returns True if everything drained, False on timeout.

    Call this before a short-lived script exits or at the end of a serverless
    invocation, where the automatic atexit drain may not run before the process
    is frozen or killed.
    """
    import time as _time
    from concurrent.futures import wait as _wait

    deadline = None if timeout is None else _time.monotonic() + timeout
    with _inflight_lock:
        futures = list(_inflight_futures)
        threads = list(_inflight_threads)

    remaining = None if deadline is None else max(deadline - _time.monotonic(), 0)
    _done, not_done = _wait(futures, timeout=remaining)
    ok = not not_done
    for t in threads:
        remaining = None if deadline is None else max(deadline - _time.monotonic(), 0)
        t.join(remaining)
        if t.is_alive():
            ok = False
    return ok


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

# Audio transcription/translation pricing (USD per minute of audio). Billed by
# duration, not tokens — a separate model from _PRICING above.
_AUDIO_PRICING = {
    "openai": {
        "whisper-1":             0.006,
        "gpt-4o-transcribe":     0.006,
        "gpt-4o-mini-transcribe": 0.003,
    },
}
_DEFAULT_AUDIO_RATE = 0.006


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
    """Estimate cost using longest-substring matching against the pricing
    table. Sorting keys by descending length first avoids the classic
    `gpt-4o-mini` being misclassified as `gpt-4o` because the iteration
    happened to hit the shorter key first.
    """
    provider_pricing = _PRICING.get(provider, {})
    rates = _DEFAULT_PRICING
    for key, r in sorted(provider_pricing.items(), key=lambda kv: -len(kv[0])):
        if key in model:
            rates = r
            break
    return (input_tokens / 1_000_000) * rates[0] + (output_tokens / 1_000_000) * rates[1]


def estimate_audio_cost(provider, model, audio_seconds):
    """Estimate transcription/translation cost from audio duration (seconds).

    Per-minute billing, longest-substring model matching (same scheme as
    estimate_cost) against _AUDIO_PRICING.
    """
    table = _AUDIO_PRICING.get(provider, {})
    rate = _DEFAULT_AUDIO_RATE
    for key, r in sorted(table.items(), key=lambda kv: -len(kv[0])):
        if key in model:
            rate = r
            break
    return (max(audio_seconds, 0.0) / 60.0) * rate


def report_usage(
    provider,
    model,
    input_tokens,
    output_tokens,
    tags=None,
    requested_model=None,
    cost_usd=None,
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
    # cost_usd lets callers (e.g. the audio/transcription path) supply a
    # precomputed cost that isn't token-based; otherwise estimate from tokens.
    cost = cost_usd if cost_usd is not None else estimate_cost(provider, model, input_tokens, output_tokens)
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
        # `plan` tag (spec §4.2): the customer's plan, for per-plan cost
        # attribution on the Surge side. Only sent when present.
        "plan": _truncate(merged_tags.get("plan")),
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
            resp = _opener.open(req, timeout=_REQUEST_TIMEOUT)
            _check_quota_header(resp)
        except Exception as e:
            # H8 fix: log instead of silently swallowing. Never raises into the
            # caller; opt-in diagnostics observe the drop (set_diagnostics()).
            logger.debug("Surge event report failed: %s", e)
            _emit_report_error(e)

    try:
        fut = _pool.submit(_send)
    except RuntimeError:
        # Pool has been shut down (interpreter exiting) — drop silently
        return
    with _inflight_lock:
        _inflight_futures.add(fut)
    fut.add_done_callback(_discard_future)


def track(event, tenant, properties=None):
    """Send a product event to Surge's /api/track endpoint.

    Unlike `report_usage` (cost/token attribution tied to a provider call),
    this records arbitrary product events — feature usage, lifecycle
    milestones, activation funnels — keyed by tenant.

    The `product` field is read from the globally configured `product_line`
    (set once via `configure(product_line=...)`).

    Fire-and-forget: the POST runs on a daemon thread so the caller is never
    blocked and never sees an exception. A failed request is logged as a
    warning, not raised. If `configure()` hasn't supplied both `surge_api_url`
    and `surge_api_key`, the event is dropped with a warning.

    Example:
        from surge_sdk import track
        track(
            event="parse.repo.connected",
            tenant="github_username_or_user_id",
            properties={"repo": "owner/repo", "language": "python"},
        )
    """
    _track(event, tenant, properties)


def _track(event, tenant, properties=None, product=None):
    """track() with an optional per-event `product` override.

    `product` falls back to the configured `product_line` when not given.
    """
    cfg = get_config()
    if not cfg.surge_api_url or not cfg.surge_api_key:
        logger.warning(
            "surge_sdk.track() called before configure() set surge_api_url and "
            "surge_api_key — event %r dropped.",
            event,
        )
        return

    payload = {
        "event": _truncate(event),
        "tenant": _truncate(tenant),
        "product": _truncate(product or cfg.product_line),
        "properties": properties or {},
    }

    # Snapshot config values now so the thread doesn't re-read a config that
    # may have changed (or to avoid touching the lock from the worker thread).
    api_url = cfg.surge_api_url.rstrip("/")
    api_key = cfg.surge_api_key

    def _send():
        try:
            import json
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            }
            req = urllib.request.Request(
                f"{api_url}/api/track",
                data=json.dumps(payload).encode(),
                headers=headers,
                method="POST",
            )
            # C4: use _opener (no redirects) to prevent Bearer token leakage.
            resp = _opener.open(req, timeout=_REQUEST_TIMEOUT)
            _check_quota_header(resp)
        except Exception as e:
            logger.warning("Surge track() failed for event %r: %s", event, e)
            _emit_report_error(e)
        finally:
            with _inflight_lock:
                _inflight_threads.discard(t)

    # Fire-and-forget on a daemon thread so it never holds up interpreter exit.
    # Registered so flush() can wait for it (serverless/short-lived scripts).
    t = threading.Thread(target=_send, daemon=True, name="surge-sdk-track")
    with _inflight_lock:
        _inflight_threads.add(t)
    t.start()


def track_quota_event(kind, product_line, customer_id, plan=None, **fields):
    """Report a quota event to Surge (spec §1.5) — a convenience wrapper around
    track() for the other products to use.

    ``kind`` is ``"ceiling_hit"`` or ``"limit_hit"`` (or a full ``"quota.*"``
    event name). The event is scoped/named by ``customer_id``. ``plan`` plus any
    extra keyword fields (``spend_usd``, ``ceiling_usd``, ``unit``, ``used``,
    ``limit``, …) are passed through as event properties; None values are
    dropped. Fire-and-forget, like track().

    Example:
        track_quota_event(
            "ceiling_hit", product_line="forge", customer_id="cust_42",
            plan="maker", spend_usd=9.12, ceiling_usd=9.00,
        )
    """
    event = kind if str(kind).startswith("quota.") else f"quota.{kind}"
    properties = {"product_line": product_line, "customer_id": customer_id, "plan": plan}
    properties.update(fields)
    properties = {k: v for k, v in properties.items() if v is not None}
    # The event's top-level `product` is the product_line passed here, not
    # only the globally configured one — a shared service reporting quota
    # events for several products must attribute each to the right product.
    _track(
        event,
        tenant=str(customer_id or product_line or "unknown"),
        properties=properties,
        product=product_line,
    )
