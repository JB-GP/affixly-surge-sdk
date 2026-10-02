# Surge SDK — Getting Started

Track what your AI is actually costing you. The Surge SDK wraps your existing Anthropic, OpenAI, or Gemini client with a one-line import change — no proxy, no infrastructure, no code rewrite.

---

## What you'll have after this guide

- Real-time AI spend tracking in the Surge dashboard
- Cost breakdown by product line, feature, and customer
- Anomaly alerts when daily spend spikes
- Budget thresholds that warn you before the invoice arrives

Time to set up: **under 5 minutes.**

---

## 1. Create your Surge account

1. Go to [your Surge instance URL] and click **Sign in with Google**
2. You'll land on the Overview page — empty for now

---

## 2. Generate your SDK API key

1. Open **Settings** (bottom of the sidebar)
2. Click the **SDK** tab
3. Click **Generate API key**
4. Copy the key — it starts with `surge_sk_` and is only shown in full once

You'll need two values going forward:
- **Surge API URL**: your Surge backend URL (provided by your admin)
- **SDK API key**: the key you just generated

---

## 3. Install the SDK

```bash
pip install affixly-surge-sdk
```

Install alongside whichever provider SDK you use:

```bash
pip install affixly-surge-sdk anthropic       # Anthropic (Claude)
pip install affixly-surge-sdk openai          # OpenAI (GPT, Whisper)
pip install affixly-surge-sdk google-genai    # Google Gemini
pip install "affixly-surge-sdk[all]"          # All providers
```

> The PyPI package name is `affixly-surge-sdk` (hyphenated). The Python import path is `surge_sdk` (underscored) — `from surge_sdk import ...` everywhere below.

---

## 4. Configure (once, at app startup)

Add this to your application's startup — before any AI calls are made.

```python
from surge_sdk import configure

configure(
    surge_api_url="https://your-surge-backend-url",
    surge_api_key="surge_sk_your_key_here",
    product_line="your-app-name",
)
```

| Parameter | Required | Description |
|---|---|---|
| `surge_api_url` | Yes | Your Surge backend URL |
| `surge_api_key` | Yes | SDK API key from Settings → SDK |
| `product_line` | No | Top-level cost bucket (e.g. `"my-app"`, `"api-service"`) |
| `default_tags` | No | Dict of tags merged into every request |
| `model_overrides` | No | Dict mapping requested model → actual model (see [Model overrides](#model-overrides)) |

---

## 5. Swap your import

Change one line per provider. Everything else in your code stays identical.

### Anthropic

```python
# Before
import anthropic

# After
from surge_sdk import anthropic
```

```python
client = anthropic.Anthropic(api_key="sk-ant-...")

response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Hello"}],
)

# Works exactly as before. Surge tracks it automatically.
```

### OpenAI

```python
# Before
import openai

# After
from surge_sdk import openai
```

```python
client = openai.OpenAI(api_key="sk-...")

response = client.chat.completions.create(
    model="gpt-4o",
    messages=[{"role": "user", "content": "Hello"}],
)
```

### Google Gemini

```python
# Before
from google import genai

# After
from surge_sdk import gemini as genai
```

```python
client = genai.Client(api_key="AIza...")

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents="Hello",
)
```

---

## 6. Add feature tags (optional)

Tags let you see cost broken down by feature or customer — not just by model.

Add `surge_tags` to any API call:

```python
response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    messages=[{"role": "user", "content": prompt}],
    surge_tags={
        "feature": "document-generation",
        "customer_id": "cust_abc123",
    },
)
```

Tags are merged with your `default_tags` from `configure()`. Per-request values take precedence.

### Tag reference

| Tag | Purpose | Example values |
|---|---|---|
| `product_line` | Set in `configure()` — which app/service | `"my-app"`, `"api"`, `"internal-tools"` |
| `feature` | Which feature made this call | `"chat"`, `"search"`, `"summarize"` |
| `customer_id` | Which of your customers triggered it | `"cust_123"`, `"tenant_42"` |
| `plan` | The customer's plan — for per-plan cost attribution | `"starter"`, `"maker"`, `"business"` |

All tags are optional. Use as many or as few as you need. `plan` can be set per
call in `surge_tags` (as above) or once for every call in
`configure(default_tags={"plan": ...})`; it is forwarded as the event's `plan`
field so the dashboard can break spend down by plan tier.

---

## Model overrides

The SDK can redirect calls to a different model than the one declared at the
call site. The call site keeps declaring intent ("use Opus here"); the SDK
enforces the actual model used ("but for this tenant, use Sonnet"). Useful
for multi-tenant SaaS where plan tier should determine model capability.

### Global overrides — `model_overrides` in `configure()`

A static map applied to every call the SDK intercepts:

```python
from surge_sdk import configure

configure(
    surge_api_url="...",
    surge_api_key="surge_sk_...",
    product_line="my-app",
    model_overrides={
        "claude-opus-4-5": "claude-sonnet-4-6",   # all Opus calls become Sonnet
        "claude-opus-4-6": "claude-sonnet-4-6",   # future-proofed
    },
)
```

### Per-request overrides — `surge_model` kwarg

For dynamic per-call routing (typical multi-tenant pattern: resolve the
tenant's plan at request time, pick a model):

```python
PLAN_MODEL_MAP = {
    "starter":  "claude-haiku-4-5",
    "solo_pro": "claude-sonnet-4-6",
    "business": "claude-opus-4-5",
}

def get_tenant_model(tenant_id):
    plan = get_tenant_plan(tenant_id)
    return PLAN_MODEL_MAP.get(plan, "claude-sonnet-4-6")

response = client.messages.create(
    model="claude-opus-4-5",                       # intent declared in code
    max_tokens=1024,
    messages=[{"role": "user", "content": prompt}],
    surge_model=get_tenant_model(tenant_id),       # control — resolved at runtime
    surge_tags={"feature": "chat", "customer_id": str(tenant_id)},
)
```

`surge_model` and `surge_tags` are both stripped from the request before it
reaches the provider SDK.

### Precedence

1. `surge_model` (per-request) — wins outright
2. `model_overrides` (global) — applies when there's no per-request value
3. `model=` in the call — used unchanged when neither override matches

### What the dashboard shows

When an override fires, Surge logs both the requested and the actual model
on the event. The Usage table reveals a "Requested" column showing the
original model the call asked for. The Overview surfaces a "Savings from
model overrides" card with the cost delta this month.

### What this does *not* do

- The SDK does not validate that the override target is a real model name. A
  typo will reach the provider unchanged and produce a provider-side error.
- The SDK does not block or rate-limit based on tier. That's app logic.
- The SDK does not match model names by regex or wildcard. Exact match only.
- Streaming calls now report usage (0.3.0+) and overrides apply to them
  exactly like non-streaming calls — same `surge_model` kwarg, same
  precedence, same payload fields.

---

## Product event tracking

AI cost is one signal; what your users actually *do* is another. Use
`track()` to record arbitrary product events — feature usage, lifecycle
milestones, activation funnels — keyed by tenant. These are separate from
the cost/token events the provider wrappers emit.

```python
from surge_sdk import track

track(
    event="parse.repo.connected",
    tenant="github_username_or_user_id",
    properties={"repo": "owner/repo", "language": "python"},
)
```

| Argument | Required | Description |
|---|---|---|
| `event` | Yes | Event name, e.g. `"parse.repo.connected"`, `"export.completed"` |
| `tenant` | Yes | Who triggered it — your user/tenant identifier |
| `properties` | No | Dict of extra context attached to the event |

The `product` field is filled automatically from the `product_line` you set
in `configure()`, so there's nothing extra to pass. Under the hood `track()`
POSTs `{event, tenant, product, properties}` to `/api/track` with your SDK
API key.

Same operational guarantees as usage reporting:

- **Non-blocking** — the POST runs on a background daemon thread; `track()`
  returns immediately.
- **Never raises** — a failed request is logged as a warning, never
  propagated to your code.
- **Drops safely** — if `configure()` hasn't supplied `surge_api_url` and
  `surge_api_key`, the event is dropped with a warning.

### Quota events — `track_quota_event()`

`track_quota_event()` is a convenience wrapper over `track()` for reporting a
spend-ceiling or quota-limit hit (the pattern the other Affixly products use).
It posts a `quota.ceiling_hit` / `quota.limit_hit` event scoped to a customer.

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

| Argument | Required | Description |
|---|---|---|
| `kind` | Yes | `"ceiling_hit"` or `"limit_hit"` — or a full `"quota.*"` name, used as-is |
| `product_line` | Yes | Which product line hit the ceiling/limit |
| `customer_id` | Yes | The customer the event is scoped to (also used as the `tenant`) |
| `plan` | No | The customer's plan |
| `**fields` | No | Extra event properties (`spend_usd`, `ceiling_usd`, `unit`, `used`, `limit`, …) |

`plan` and the extra keyword fields become event properties; `None` values are
dropped. Fire-and-forget, with the same guarantees as `track()`.

---

## 7. Verify it's working

1. Run your application and trigger a few AI calls
2. Open Surge → **Overview**
   - "Cost by product line" card should show your `product_line`
   - Daily spend chart should have new data points
3. Open Surge → **Usage**
   - Individual records with your model, token counts, and estimated cost
4. Open Surge → **Overview** → "Model pricing comparison"
   - Shows what the same workload would cost on alternative models

If the Overview is empty after a few calls:
- Check that `surge_api_url` is correct and reachable from your app
- Check that `surge_api_key` matches the key shown in Settings → SDK
- Look for import errors in your application logs (the SDK logs nothing by default — it's designed to be invisible)

---

## How it works

```
Your app calls the provider SDK (Anthropic, OpenAI, Gemini)
  → Surge SDK wrapper adds metadata to the request
  → Request goes directly to the provider (no proxy, no detour)
  → Provider returns response with token counts
  → SDK reads response.usage (input_tokens, output_tokens)
  → SDK estimates cost from built-in pricing table
  → SDK POSTs usage event to your Surge backend (background thread)
  → Your app receives the response unchanged
```

**Latency impact**: zero network hops added to the provider call. The Surge report runs on a background thread after your code has already received the response.

---

## Failure semantics

Two kinds of failure are kept strictly separate, and they behave differently:

### Provider / API failure

An error from the underlying Anthropic, OpenAI, or Gemini call — authentication,
rate limit, bad request, timeout, network — **propagates to your code
unchanged**. The SDK does not catch, wrap, or swallow provider errors. Any
`try/except` you already have around the provider call keeps working exactly as
before. For convenience, the provider exception classes are re-exported from the
wrapper modules:

```python
from surge_sdk import anthropic

try:
    resp = client.messages.create(model="claude-sonnet-4-6", max_tokens=1024,
                                   messages=[{"role": "user", "content": prompt}])
except anthropic.RateLimitError:
    ...   # same exception you'd catch from the bare SDK
```

### Surge reporting failure

A failure to send the usage/track report to your Surge backend is **isolated and
never raised** into your code. It is logged through the `surge_sdk` logger
(usage reports at `DEBUG`, `track()` at `WARNING`) and is otherwise invisible —
your application's behavior does not change whether Surge is reachable or not.

To observe dropped reports without changing that behavior, opt in with
`set_diagnostics()`:

```python
from surge_sdk import set_diagnostics

# on_report_error(exc) is called best-effort whenever a report fails to send.
set_diagnostics(on_report_error=lambda exc: metrics.increment("surge.report_dropped"))

set_diagnostics()        # pass nothing (or None) to clear the handler
```

The handler never changes failure behavior — Surge still never raises. It only
lets you see that a report was dropped.

### Over-quota behavior

When your Surge event quota is exhausted, the backend answers event reports with
the header `X-Surge-Quota: exceeded`. The SDK then emits a Python
`warnings.warn` **once per process** and never raises. New events are dropped
server-side and don't count against your plan. This is expected at the
free/over-quota boundary — raise the plan limit to resume ingestion.

---

## Process lifecycle

Reports are sent on background workers, so the only operational concern is
making sure they drain before the process exits.

| Context | What to do |
|---|---|
| **Long-running server** | Nothing. Fire-and-forget is correct — workers send reports while the process keeps running. |
| **Short-lived script** | Nothing in the normal case. An `atexit` handler drains outstanding reports on a clean interpreter exit. |
| **Serverless / FaaS** | Call `flush()` at the end of each invocation. The platform may freeze or kill the process before the `atexit` drain runs. |

### `flush()`

```python
from surge_sdk import flush

ok = flush(timeout=2.0)   # block until reports drain, or 2s elapses
```

`flush(timeout=None)` blocks until all outstanding usage/track reports have been
sent, or `timeout` seconds elapse. Returns `True` if everything drained, `False`
on timeout. With no timeout it waits indefinitely.

### Serverless example

```python
from surge_sdk import configure, flush

configure(surge_api_url=..., surge_api_key=..., product_line="my-app")

def handler(event, context):
    result = do_work(event)      # AI calls reported in the background
    flush(timeout=2.0)           # drain before the platform freezes the process
    return result
```

Without the `flush()` call, a serverless platform can freeze the container the
instant your handler returns, dropping reports that hadn't been sent yet.

---

## Async support

The SDK wraps both the sync and async clients for Anthropic and OpenAI. Gemini
is sync-only, matching the upstream SDK's wrapping surface — there is no async
Gemini client.

```python
# Anthropic
from surge_sdk import anthropic
client = anthropic.Anthropic()
async_client = anthropic.AsyncAnthropic()

# OpenAI
from surge_sdk import openai
client = openai.OpenAI()
async_client = openai.AsyncOpenAI()

# Gemini (sync only)
from surge_sdk import gemini as genai
client = genai.Client()
```

---

## Multiple providers in one app

If your application uses more than one provider, each import is independent. They all share the same `configure()` call.

```python
from surge_sdk import anthropic, openai, configure

configure(
    surge_api_url="https://your-surge-backend-url",
    surge_api_key="surge_sk_...",
    product_line="my-app",
)

# Anthropic for generation
claude = anthropic.Anthropic(api_key="sk-ant-...")
result = claude.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    messages=[{"role": "user", "content": "Write a summary"}],
    surge_tags={"feature": "summarize"},
)

# OpenAI for embeddings or chat
gpt = openai.OpenAI(api_key="sk-...")
chat = gpt.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Classify this text"}],
    surge_tags={"feature": "classify"},
)
```

Both calls show up in the same Surge dashboard under the same `product_line`, split by provider and feature.

---

## Setting a budget

Once data is flowing, set a spend limit:

1. Open **Settings → Billing**
2. Enter a monthly budget (e.g. $500)
3. Toggle alert thresholds: 50%, 80%, 100%
4. Save

Surge checks your spend against the budget after every sync and creates alerts when thresholds are crossed.

---

## Viewing cost attribution

### By product line
**Overview** → "Cost by product line" card — appears automatically when tagged data exists.

### By feature or customer
Use the API:

```
GET /api/usage/by-tag?group_by=feature
GET /api/usage/by-tag?group_by=customer_id
GET /api/usage/by-tag?group_by=product_line&from=2026-04-01&to=2026-04-30
```

Response:
```json
[
  {
    "tag": "document-generation",
    "total_cost": 12.45,
    "input_tokens": 1840000,
    "output_tokens": 620000,
    "requests": 1240
  },
  {
    "tag": "chat",
    "total_cost": 3.82,
    "input_tokens": 490000,
    "output_tokens": 160000,
    "requests": 380
  }
]
```

---

## Removing the SDK

The SDK is fully reversible. To remove:

1. Change `from surge_sdk import anthropic` back to `import anthropic` (same for openai/gemini)
2. Remove `surge_tags={...}` and `surge_model=...` keyword arguments from any call sites
3. Remove the `configure()` call
4. Remove environment variables (`SURGE_API_URL`, `SURGE_SDK_KEY`)
5. `pip uninstall affixly-surge-sdk`

Your application works identically without the SDK. Previously recorded data stays in Surge.

---

## Capability matrix

Which methods the wrapper tracks, per provider, and where sync / async /
streaming are supported.

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

Sync clients: `Anthropic` / `OpenAI` / `Client`. Async clients:
`AsyncAnthropic` / `AsyncOpenAI`. Gemini is sync-only.

**OpenAI audio transcription** tracks `whisper-1`, `gpt-4o-transcribe`, and
`gpt-4o-mini-transcribe`. Transcription is billed per audio-minute, not per
token: the SDK reads `response.duration`, which the OpenAI API returns only when
you pass `response_format="verbose_json"`. Without duration the call is still
reported, with cost `0`.

---

## Compatibility & versioning

- **Python:** 3.9+ (per `requires-python` and the classifiers in
  `pyproject.toml`).
- **Provider SDKs** (install the extra you use): `anthropic>=0.25,<2`,
  `openai>=1,<3`, `google-genai>=1,<2`.
- **SemVer:** the public API exported from `surge_sdk` (`configure`,
  `get_config`, `track`, `track_quota_event`, `flush`, `set_diagnostics`)
  follows semantic versioning — breaking changes bump the major version.
- **Version source:** single-sourced in `pyproject.toml` and read back at
  runtime from installed package metadata as `surge_sdk.__version__`, so there
  is no hand-maintained duplicate to drift.

See [`CHANGELOG.md`](../CHANGELOG.md) for release notes.

---

## FAQ

**Does the SDK proxy my API calls?**
No. Your requests go directly to the provider. The SDK adds metadata before the call and reads usage from the response after.

**What if Surge is down?**
Nothing happens. The background report is dropped silently. Your AI calls work exactly as if the SDK wasn't installed.

**Does the SDK see my API key?**
Yes — it wraps your provider client, so it has access to the key you pass. This is the same trust model as any SDK wrapper. The key is never sent to Surge.

**How accurate is the cost estimate?**
The SDK estimates cost using the provider's published per-token pricing. For providers that return actual billed costs in their usage API (OpenAI), Surge can supplement with actual figures via the Providers sync. The SDK estimate is typically within 1-2% of the actual bill.

**Can I use the SDK in production?**
Yes. The reporting thread is non-blocking and fault-tolerant. It's designed to be invisible in production workloads.

**What about streaming responses?**
Streaming is tracked as of 0.3.0. For Anthropic `messages.create(stream=True)` and `messages.stream()`, token counts are absorbed from the stream's `message_start` and `message_delta` events and reported once iteration completes (or the context manager exits — whichever comes first). For OpenAI `chat.completions.create(stream=True)`, the SDK forces `stream_options.include_usage=True` so the final chunk carries cumulative usage; callers iterating raw chunks will see one extra final chunk. For Gemini `generate_content_stream()`, token counts are read from the final response's `usage_metadata`. Early `break` from iteration still reports whatever was collected — partial usage is correct usage.
