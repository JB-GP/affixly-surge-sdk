"""Reporting semantics: never raise into the caller, bounded flush, quota
signal, diagnostics without secrets, quota-event attribution, plan tag."""

import logging
import threading
import time
import warnings

import pytest

import surge_sdk
from surge_sdk import _reporter

SECRET = "sk_surge_SECRET_TEST_KEY_123"


# ── Unconfigured use is a warning, never an error ────────────────────────────

class TestUnconfigured:
    def test_track_without_configure_warns_and_does_not_raise(self, caplog):
        with caplog.at_level(logging.WARNING, logger="surge_sdk"):
            surge_sdk.track("app.opened", tenant="t1", properties={"a": 1})
        msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
        assert any("dropped" in m and "app.opened" in m for m in msgs)

    def test_track_with_url_but_no_key_warns(self, caplog, stub):
        surge_sdk.configure(surge_api_url=stub.url)  # no key
        with caplog.at_level(logging.WARNING, logger="surge_sdk"):
            surge_sdk.track("app.opened", tenant="t1")
        assert any(r.levelno == logging.WARNING for r in caplog.records)
        assert surge_sdk.flush(timeout=2) is True
        assert stub.requests == []  # nothing sent

    def test_quota_event_without_configure_does_not_raise(self, caplog):
        with caplog.at_level(logging.WARNING, logger="surge_sdk"):
            surge_sdk.track_quota_event("ceiling_hit", product_line="forge", customer_id="c1")
        assert any(r.levelno == logging.WARNING for r in caplog.records)

    def test_usage_report_without_url_is_silent_noop(self):
        # No URL -> nothing to send; must not raise or block.
        _reporter.report_usage("anthropic", "claude-sonnet-4-6", 10, 5)
        assert surge_sdk.flush(timeout=1) is True


# ── X-Surge-Quota: exceeded -> warn once per process, never raise ────────────

class TestQuotaHeader:
    def test_warns_exactly_once_and_never_raises(self, configured):
        configured.status = 202
        configured.headers = {"X-Surge-Quota": "exceeded"}
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            for _ in range(3):
                _reporter.report_usage("anthropic", "claude-sonnet-4-6", 10, 5)
            surge_sdk.track("app.opened", tenant="t1")
            assert surge_sdk.flush(timeout=5) is True
        quota = [w for w in caught if "quota exceeded" in str(w.message)]
        assert len(quota) == 1
        assert len(configured.requests) == 4

    def test_no_warning_without_header(self, configured):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            _reporter.report_usage("anthropic", "claude-sonnet-4-6", 10, 5)
            assert surge_sdk.flush(timeout=5) is True
        assert not [w for w in caught if "quota" in str(w.message)]


# ── flush(timeout) is bounded and returns ────────────────────────────────────

class TestFlush:
    def test_flush_with_nothing_pending_returns_true(self):
        assert surge_sdk.flush(timeout=0.1) is True

    def test_flush_timeout_is_bounded_and_reports_false(self, configured):
        configured.hold = threading.Event()  # server hangs until released
        surge_sdk.track("slow.event", tenant="t1")
        _reporter.report_usage("anthropic", "claude-sonnet-4-6", 10, 5)
        assert configured.received.wait(5)

        t0 = time.monotonic()
        result = surge_sdk.flush(timeout=0.3)
        elapsed = time.monotonic() - t0
        assert result is False
        assert elapsed < 1.5, f"flush(timeout=0.3) took {elapsed:.2f}s"

        configured.hold.set()
        assert surge_sdk.flush(timeout=5) is True

    def test_flush_drains_sent_reports(self, configured):
        for i in range(5):
            surge_sdk.track("e", tenant=f"t{i}")
        assert surge_sdk.flush(timeout=5) is True
        assert len(configured.bodies("/api/track")) == 5


# ── on_report_error gets sanitized failures: no keys, no payload ─────────────

class TestDiagnostics:
    def _collect(self):
        got = []
        done = threading.Event()

        def handler(exc):
            got.append(exc)
            done.set()

        surge_sdk.set_diagnostics(on_report_error=handler)
        return got, done

    @staticmethod
    def _assert_clean(exc):
        assert isinstance(exc, Exception)
        texts = [str(exc), repr(exc)] + [repr(a) for a in exc.args]
        texts += [repr(v) for v in vars(exc).values()]
        for t in texts:
            assert SECRET not in t
            assert "cust_private_42" not in t
        # No traceback / chained cause: frame locals hold the Authorization
        # header and the payload, and error reporters (e.g. Sentry) capture
        # frame locals by default.
        assert exc.__traceback__ is None
        assert exc.__cause__ is None and exc.__context__ is None

    def test_http_error_is_sanitized(self, configured):
        configured.status = 500
        configured.body = b'{"error": "boom"}'
        got, done = self._collect()
        surge_sdk.track("e", tenant="cust_private_42", properties={"customer_id": "cust_private_42"})
        assert done.wait(5)
        exc = got[0]
        self._assert_clean(exc)
        assert getattr(exc, "status", None) == 500
        assert getattr(exc, "endpoint", None) == "/api/track"

    def test_connection_error_is_sanitized(self, stub):
        url = stub.url
        stub.close()  # nothing listening any more
        surge_sdk.configure(surge_api_url=url, surge_api_key=SECRET)
        got, done = self._collect()
        _reporter.report_usage("anthropic", "claude-sonnet-4-6", 1, 1,
                               tags={"customer_id": "cust_private_42"})
        assert done.wait(10)
        exc = got[0]
        self._assert_clean(exc)
        assert getattr(exc, "endpoint", None) == "/api/events"
        assert getattr(exc, "status", "missing") is None

    def test_handler_exception_never_reaches_caller(self, configured):
        configured.status = 500

        def bad_handler(exc):
            raise RuntimeError("handler bug")

        surge_sdk.set_diagnostics(on_report_error=bad_handler)
        surge_sdk.track("e", tenant="t1")
        assert surge_sdk.flush(timeout=5) is True

    def test_no_handler_no_raise(self, configured):
        configured.status = 503
        surge_sdk.track("e", tenant="t1")
        assert surge_sdk.flush(timeout=5) is True


# ── track_quota_event sets the event's product ───────────────────────────────

class TestQuotaEvent:
    def test_product_is_the_quota_events_product_line(self, configured):
        surge_sdk.track_quota_event(
            "ceiling_hit", product_line="forge", customer_id="cust_42",
            plan="maker", spend_usd=9.12, ceiling_usd=9.0, unused=None,
        )
        assert surge_sdk.flush(timeout=5) is True
        (body,) = configured.bodies("/api/track")
        assert body["event"] == "quota.ceiling_hit"
        assert body["product"] == "forge"  # not the configured "global-app"
        assert body["tenant"] == "cust_42"
        props = body["properties"]
        assert props["product_line"] == "forge"
        assert props["plan"] == "maker"
        assert props["spend_usd"] == 9.12
        assert "unused" not in props  # None values dropped

    def test_full_event_name_is_kept(self, configured):
        surge_sdk.track_quota_event("quota.limit_hit", product_line="wire", customer_id="c")
        assert surge_sdk.flush(timeout=5) is True
        assert configured.bodies("/api/track")[0]["event"] == "quota.limit_hit"

    def test_plain_track_still_uses_configured_product(self, configured):
        surge_sdk.track("app.opened", tenant="t1")
        assert surge_sdk.flush(timeout=5) is True
        assert configured.bodies("/api/track")[0]["product"] == "global-app"


# ── plan tag forwarded on usage reports ──────────────────────────────────────

class TestPlanTag:
    def test_plan_from_per_request_tags(self, configured):
        _reporter.report_usage("anthropic", "claude-sonnet-4-6", 10, 5,
                               tags={"plan": "pro", "customer_id": "c1"})
        assert surge_sdk.flush(timeout=5) is True
        (body,) = configured.bodies("/api/events")
        assert body["plan"] == "pro"
        assert body["customer_id"] == "c1"
        assert body["product_line"] == "global-app"

    def test_plan_from_default_tags(self, configured):
        surge_sdk.configure(default_tags={"plan": "team"})
        _reporter.report_usage("anthropic", "claude-sonnet-4-6", 10, 5)
        assert surge_sdk.flush(timeout=5) is True
        assert configured.bodies("/api/events")[0]["plan"] == "team"

    def test_no_plan_is_null(self, configured):
        _reporter.report_usage("anthropic", "claude-sonnet-4-6", 10, 5)
        assert surge_sdk.flush(timeout=5) is True
        assert configured.bodies("/api/events")[0]["plan"] is None

    def test_bearer_key_sent_to_surge(self, configured):
        _reporter.report_usage("anthropic", "claude-sonnet-4-6", 10, 5)
        assert surge_sdk.flush(timeout=5) is True
        req = configured.requests[0]
        assert req["headers"].get("Authorization") == f"Bearer {SECRET}"
