# affixly-surge-sdk

Lightweight cost-attribution wrapper for the Anthropic, OpenAI, and Google Gemini Python SDKs. Track AI spend by product line, feature, and customer with a one-line import change — no proxy, no infrastructure, no code rewrite.

> **PyPI distribution name:** `affixly-surge-sdk`. **Python import name:** `surge_sdk`. They differ because `surge-sdk` was already taken on PyPI by an unrelated project — the import name we control stays clean.

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

## How it works

- The wrapper intercepts `messages.create()` (or the equivalent for OpenAI / Gemini), reads token counts from the response, and POSTs a usage event to your Surge backend on a background thread.
- Your AI calls go directly to the provider — no proxy, no added latency.
- If Surge is unreachable, the report is dropped silently. Your application is never affected.

## Supported providers

| Provider | Import | What's tracked |
|---|---|---|
| Anthropic | `from surge_sdk import anthropic` | `messages.create()`, `messages.stream()` |
| OpenAI | `from surge_sdk import openai` | `chat.completions.create()` |
| Google Gemini | `from surge_sdk import gemini as genai` | `models.generate_content()` |

Both sync and async clients are supported for all providers.

## Documentation

Full guide: see [`docs/getting-started.md`](docs/getting-started.md).

## License

MIT — see [LICENSE](LICENSE).
