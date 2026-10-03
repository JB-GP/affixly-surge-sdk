"""surge_sdk.anthropic imports on both anthropic majors (0.x keeps
HUMAN_PROMPT / AI_PROMPT; 1.x removed them) and forwards the plan tag.

A fake `anthropic` module is installed via monkeypatch, so neither major
needs to be installed and nothing touches the network except the local stub.
"""

import importlib
import sys
import types

import pytest

import surge_sdk


class _Usage:
    def __init__(self, i, o):
        self.input_tokens = i
        self.output_tokens = o


class _Response:
    def __init__(self, model):
        self.model = model
        self.usage = _Usage(120, 30)


class _FakeMessages:
    def __init__(self):
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Response(kwargs.get("model", "unknown"))


def _fake_anthropic(legacy_prompts: bool) -> types.ModuleType:
    mod = types.ModuleType("anthropic")

    class Anthropic:
        def __init__(self, *a, **kw):
            self._fake_messages = _FakeMessages()

        @property
        def messages(self):
            return self._fake_messages

    class AsyncAnthropic(Anthropic):
        pass

    mod.Anthropic = Anthropic
    mod.AsyncAnthropic = AsyncAnthropic
    for name in ("APIError", "AuthenticationError", "BadRequestError", "NotFoundError",
                 "RateLimitError", "APIConnectionError", "APITimeoutError"):
        setattr(mod, name, type(name, (Exception,), {}))
    if legacy_prompts:
        mod.HUMAN_PROMPT = "\n\nHuman:"
        mod.AI_PROMPT = "\n\nAssistant:"
    return mod


def _import_wrapper(monkeypatch, legacy_prompts):
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic(legacy_prompts))
    monkeypatch.delitem(sys.modules, "surge_sdk.anthropic", raising=False)
    wrapper = importlib.import_module("surge_sdk.anthropic")
    # Don't leak a wrapper bound to the fake module into other tests.
    monkeypatch.delitem(sys.modules, "surge_sdk.anthropic", raising=False)
    return wrapper


@pytest.mark.parametrize("legacy", [True, False], ids=["anthropic-0.x", "anthropic-1.x"])
def test_wrapper_imports_on_both_majors(monkeypatch, legacy):
    w = _import_wrapper(monkeypatch, legacy_prompts=legacy)
    assert hasattr(w, "Anthropic") and hasattr(w, "AsyncAnthropic")
    assert hasattr(w, "HUMAN_PROMPT") is legacy
    assert ("HUMAN_PROMPT" in w.__all__) is legacy
    assert ("AI_PROMPT" in w.__all__) is legacy
    for name in w.__all__:
        assert hasattr(w, name), name


@pytest.mark.parametrize("legacy", [True, False], ids=["anthropic-0.x", "anthropic-1.x"])
def test_plan_tag_forwarded_through_wrapper(monkeypatch, configured, legacy):
    w = _import_wrapper(monkeypatch, legacy_prompts=legacy)
    client = w.Anthropic(api_key="sk-ant-fake")
    resp = client.messages.create(
        model="claude-sonnet-4-6", max_tokens=10, messages=[],
        surge_tags={"plan": "builder", "customer_id": "cust_7", "feature": "chat"},
    )
    assert resp.usage.input_tokens == 120
    # surge_tags never reaches the provider.
    sent = client._fake_messages.calls[0]
    assert "surge_tags" not in sent

    assert surge_sdk.flush(timeout=5) is True
    (body,) = configured.bodies("/api/events")
    assert body["provider"] == "anthropic"
    assert body["plan"] == "builder"
    assert body["customer_id"] == "cust_7"
    assert body["input_tokens"] == 120 and body["output_tokens"] == 30
