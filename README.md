# affixly-surge-sdk

Lightweight cost-attribution wrapper for the Anthropic, OpenAI, and Google Gemini Python SDKs. Track AI spend by product line, feature, and customer with a one-line import change — no proxy, no infrastructure, no code rewrite.

> **PyPI distribution name:** `affixly-surge-sdk`. **Python import name:** `surge_sdk`. They differ because `surge-sdk` was already taken on PyPI by an unrelated project — the import name we control stays clean.

> Using Node.js / TypeScript? See [`affixly-surge-sdk` on npm](https://www.npmjs.com/package/affixly-surge-sdk) — same interface, same event shape ([source](https://github.com/JB-GP/affixly-surge-sdk-node)).

## Install

```bash
pip install affixly-surge-sdk
```

Install alongside whichever provider SDK you use:

```bash
pip install "affixly-surge-sdk[anthropic]"   # Anthropic (Claude)
pip install "affixly-surge-sdk[openai]"      # OpenAI (GPT)
pip install "affixly-surge-sdk[gemini]"      # Google Gemini
pip install "affixly-surge-sdk[all]"         # All three
```

## Quick start

```python
from surge_sdk import anthropic, configure

configure(
    surge_api_url="https://your-surge-backend-url",
    surge_api_key="surge_sk_your_key_here",
    product_line="my-app",
)

client = anthropic.Anthropic(api_key="sk-ant-...")
response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Hello"}],
)
# Tracked automatically. No further code changes needed.
```

Get your `surge_api_key` from your Surge dashboard at **Settings → SDK → Generate API key**.

## Per-call tags

Attribute spend to a specific feature, customer, or plan:

```python
response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    messages=[...],
    surge_tags={"feature": "summarize", "customer_id": "cust_abc123", "plan": "maker"},
)
```

The wrappers read tags from the `surge_tags` kwarg (stripped before the request
reaches the provider). `plan` is forwarded as the event's `plan` field for
per-plan cost attribution on the dashboard. Set it per call as above, or once
for every call via `configure(default_tags={"plan": ...})`. Per-call values win
over `default_tags`.

## Model overrides

Redirect calls to a different model than the call site declares — useful for
multi-tenant plan tiering (Starter → Haiku, Business → Opus) without touching
every call site:

```python
# Global rule — applies to every call the SDK intercepts
configure(
    surge_api_url="...",
    model_overrides={
        "claude-opus-4-6": "claude-sonnet-4-6",   # all Opus calls become Sonnet
    },
)

# Per-call rule — wins over the global map
response = client.messages.create(
    model="claude-opus-4-6",                  # intent declared in code
    max_tokens=1024,
    messages=[...],
    surge_model=get_tenant_model(tenant_id),  # runtime tier resolution
    surge_tags={"feature": "chat", "customer_id": str(tenant_id)},
)
```

The dashboard logs both the requested and actual model on every override,
plus a "Savings from model overrides" card showing the cost delta over time.

## Product event tracking

Beyond AI cost, you can record arbitrary product events — feature usage,
lifecycle milestones, activation funnels — keyed by tenant. The `product`
comes from the `product_line` you set in `configure()`:

```python
from surge_sdk import track

track(
    event="parse.repo.connected",
    tenant="github_username_or_user_id",
    properties={"repo": "owner/repo", "language": "python"},
)
```

This POSTs `{event, tenant, product, properties}` to `/api/track` on a
background thread. Like usage reporting, it's fire-and-forget: the caller is
never blocked and never sees an exception. If Surge isn't configured (no
`surge_api_url` / `surge_api_key`) or the request fails, a warning is logged
and the event is dropped — your application is never affected.

## Quota events

`track_quota_event()` is the helper the other Affixly products use to report a
spend-ceiling or quota-limit hit. It's a thin wrapper over `track()` that posts
a `quota.ceiling_hit` / `quota.limit_hit` product event scoped to a customer.

```python
from surge_sdk import track_quota_event

track_quota_event(
    "ceiling_hit",                 # or "limit_hit", or a full "quota.*" event name
    product_line="forge",
    customer_id="cust_42",
    plan="maker",
    spend_usd=9.12,
    ceiling_usd=9.00,
)
```

`kind` is `"ceiling_hit"` or `"limit_hit"` (or a full `"quota.*"` name used
as-is). The event is keyed by `customer_id`; `plan` plus any extra keyword
fields (`spend_usd`, `ceiling_usd`, `unit`, `used`, `limit`, …) are passed
through as event properties, with `None` values dropped. Fire-and-forget, same
as `track()`.

## How it works

- The wrapper intercepts `messages.create()` (or the equivalent for OpenAI / Gemini), reads token counts from the response, and POSTs a usage event to your Surge backend on a background thread.
- Your AI calls go directly to the provider — no proxy, no added latency.
- If Surge is unreachable the report is dropped; your application is never affected. See [Failure semantics](#failure-semantics) for what "dropped" means and how to observe it.

## Failure semantics

The SDK keeps two kinds of failure strictly separate:

- **Provider / API failure** — an error from the underlying Anthropic, OpenAI,
  or Gemini call (auth, rate limit, bad request, timeout, network) propagates to
  your code **unchanged**. Surge never catches, wraps, or swallows it. Your
  existing `try/except` around the provider call keeps working exactly as
  before. The provider exception classes are re-exported, e.g.
  `from surge_sdk.anthropic import RateLimitError`.
- **Surge reporting failure** — a failure to send the usage/track report to your
  Surge backend is isolated and **never raised** into your code. It is logged
  through the `surge_sdk` logger (usage reports at `DEBUG`, `track()` at
  `WARNING`) and is otherwise invisible.

To observe dropped reports (e.g. increment a metric), opt in with
`set_diagnostics()`. The handler never changes failure behavior — Surge still
never raises:

```python
from surge_sdk import set_diagnostics

set_diagnostics(on_report_error=lambda exc: metrics.increment("surge.report_dropped"))
```

The handler receives a `SurgeReportError` with `endpoint`, `status` (HTTP
status or `None`) and `reason`. It is sanitized: no SDK key, no headers, no
event payload, and no traceback, so it is safe to forward to Sentry or a log.

**Over-quota behavior.** When your Surge event quota is exhausted the backend
answers event reports with `X-Surge-Quota: exceeded`. The SDK then emits a
Python `warnings.warn` **once per process** and never raises; events are dropped
server-side and don't count against the plan. This is expected at the
free/over-quota boundary — raise the plan limit to resume ingestion.

## Capability matrix

Import once per provider; both the sync and async client classes are wrapped
where the column says so.

| Provider | Import | Wrapped method | Sync | Async | Streaming |
|---|---|---|:--:|:--:|:--:|
| Anthropic | `from surge_sdk import anthropic` | `messages.create()` | ✅ | ✅ | — |
| Anthropic | | `messages.create(stream=True)` | ✅ | ✅ | ✅ |
| Anthropic | | `messages.stream()` (context manager) | ✅ | ✅ | ✅ |
| OpenAI | `from surge_sdk import openai` | `chat.completions.create()` | ✅ | ✅ | — |
| OpenAI | | `chat.completions.create(stream=True)` | ✅ | ✅ | ✅ |
| OpenAI | | `audio.transcriptions.create()` | ✅ | ✅ | — |
| Google Gemini | `from surge_sdk import gemini as genai` | `models.generate_content()` | ✅ | — | — |
| Google Gemini | | `models.generate_content_stream()` | ✅ | — | ✅ |

Sync clients: `Anthropic` / `OpenAI` / `Client`. Async clients: `AsyncAnthropic`
/ `AsyncOpenAI`. Gemini is **sync-only** — this matches the upstream SDK's
wrapping surface; there is no async Gemini client.

**OpenAI audio transcription** (`audio.transcriptions.create()`) covers
`whisper-1`, `gpt-4o-transcribe`, and `gpt-4o-mini-transcribe`. Transcription is
billed per audio-minute, not per token: the SDK reads `response.duration`, which
the OpenAI API only returns when you pass `response_format="verbose_json"`. If
duration is absent the call is still reported, with cost `0`.

**OpenAI streaming note:** the SDK forces `stream_options.include_usage=true` on
streaming chat calls so the final chunk carries cumulative usage. Callers
iterating raw chunks will see one extra final chunk with `usage` populated —
same shape as if you'd set it yourself.

## Process lifecycle

Reports are sent on background workers, so the only thing to get right is making
sure they drain before the process goes away.

- **Long-running servers** — nothing to do. Fire-and-forget is correct; the
  background workers send reports while the process keeps running.
- **Short-lived scripts** — nothing to do in the normal case. An `atexit`
  handler drains outstanding reports on a clean interpreter exit.
- **Serverless / FaaS** — call `flush()` at the end of each invocation. The
  platform may freeze or kill the process immediately after your handler
  returns, before the `atexit` drain runs, so flush explicitly:

```python
from surge_sdk import flush

def handler(event, context):
    result = do_work(event)      # AI calls reported in the background
    flush(timeout=2.0)           # block until reports drain, or 2s elapses
    return result
```

`flush(timeout=None)` blocks until all outstanding usage/track reports have been
sent, or `timeout` seconds elapse. It returns `True` if everything drained and
`False` on timeout.

## Compatibility & versioning

- **Python:** 3.9+.
- **Provider SDKs** (install the extra you use): `anthropic>=0.25,<2`,
  `openai>=1,<3`, `google-genai>=1,<2`.
- **SemVer:** the public API in `surge_sdk.__all__` follows semantic versioning —
  breaking changes bump the major version.
- **Version:** single-sourced in `pyproject.toml` and read back at runtime from
  installed package metadata (`surge_sdk.__version__`), so there is no
  hand-maintained copy to drift.

See [`CHANGELOG.md`](CHANGELOG.md) for release notes.

## Documentation

Full guide: see [`docs/getting-started.md`](docs/getting-started.md).

**Integrating with a coding agent?** Point Claude Code, Cursor, or Copilot at [`AGENTS.md`](AGENTS.md) — a step-by-step integration guide that has the agent confirm your product line and customer identifier before writing any code.

## License

MIT — see [LICENSE](LICENSE).
