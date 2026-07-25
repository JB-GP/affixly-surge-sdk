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

Attribute spend to a specific feature or customer:

```python
response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    messages=[...],
    surge_tags={"feature": "summarize", "customer_id": "cust_abc123"},
)
```

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

## How it works

- The wrapper intercepts `messages.create()` (or the equivalent for OpenAI / Gemini), reads token counts from the response, and POSTs a usage event to your Surge backend on a background thread.
- Your AI calls go directly to the provider — no proxy, no added latency.
- If Surge is unreachable, the report is dropped silently. Your application is never affected.

## Supported providers

| Provider | Import | What's tracked |
|---|---|---|
| Anthropic | `from surge_sdk import anthropic` | `messages.create()`, `messages.create(stream=True)`, `messages.stream()` (context manager) |
| OpenAI | `from surge_sdk import openai` | `chat.completions.create()`, `chat.completions.create(stream=True)` |
| Google Gemini | `from surge_sdk import gemini as genai` | `models.generate_content()`, `models.generate_content_stream()` |

Both sync and async clients are supported for all providers (Anthropic and OpenAI; Gemini sync-only matches the upstream SDK's wrapping surface).

**Streaming note for OpenAI:** the SDK forces `stream_options.include_usage=true` on streaming calls so the final chunk carries cumulative usage. Callers iterating raw chunks will see one extra final chunk with `usage` populated — same shape as if you'd set it yourself.

## Documentation

Full guide: see [`docs/getting-started.md`](docs/getting-started.md).

**Integrating with a coding agent?** Point Claude Code, Cursor, or Copilot at [`AGENTS.md`](AGENTS.md) — a step-by-step integration guide that has the agent confirm your product line and customer identifier before writing any code.

## License

MIT — see [LICENSE](LICENSE).
