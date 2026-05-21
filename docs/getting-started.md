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
pip install surge-sdk
```

Install alongside whichever provider SDK you use:

```bash
pip install surge-sdk anthropic       # Anthropic (Claude)
pip install surge-sdk openai          # OpenAI (GPT, Whisper)
pip install surge-sdk google-genai    # Google Gemini
pip install "surge-sdk[all]"          # All providers
```

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

All tags are optional. Use as many or as few as you need.

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

**Failure mode**: if Surge is unreachable, the report is silently dropped. Your application's functionality is never affected.

---

## Async support

The SDK wraps both sync and async clients for all providers:

```python
# Anthropic
from surge_sdk import anthropic
client = anthropic.Anthropic()
async_client = anthropic.AsyncAnthropic()

# OpenAI
from surge_sdk import openai
client = openai.OpenAI()
async_client = openai.AsyncOpenAI()

# Gemini
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
5. `pip uninstall surge-sdk`

Your application works identically without the SDK. Previously recorded data stays in Surge.

---

## Supported providers

| Provider | Import | What's tracked |
|---|---|---|
| Anthropic | `from surge_sdk import anthropic` | `messages.create()`, `messages.stream()` |
| OpenAI | `from surge_sdk import openai` | `chat.completions.create()` |
| Google Gemini | `from surge_sdk import gemini as genai` | `models.generate_content()` |

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
