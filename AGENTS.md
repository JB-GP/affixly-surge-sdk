# Integrating `affixly-surge-sdk` — instructions for a coding agent

**Audience:** an AI coding agent (Claude Code, Cursor, Copilot, etc.) that a
developer has asked to add Surge cost + product-event tracking to *their own*
application.

**Drop-in use:** a developer can paste this file into their repo (e.g. as
`AGENTS.md`, a Cursor rule, or a `CLAUDE.md` section) and tell their agent
"add Surge tracking." Follow the steps below in order.

Surge wraps the official Anthropic, OpenAI, and Google Gemini SDKs so every AI
call is attributed to a **product line**, a **tenant/customer**, and a
**feature** — with a one-line import change and no proxy. It can also record
arbitrary **product events** via `track()`.

---

## ⛔ STEP 0 — Gather attribution values FIRST (do this before writing code)

Surge is worthless with placeholder labels. The whole point is that spend and
events are tagged with *real* names from this app. **You (the agent) must not
invent these.** Three things must come from the developer:

| Value | What it is | Where it shows up |
|---|---|---|
| **Product line** | The name of *this* product/app/service as it should appear in the Surge dashboard. One stable string, e.g. `"parse"`, `"flow"`, `"acme-chat"`. | `productLine` / `product_line` in `configure()`; the `product` field on every event. |
| **Tenant / customer identifier** | The *stable* per-user or per-account ID this app already uses (auth user id, org id, workspace id, GitHub username, Stripe customer id…). | `customer_id` tag on AI calls; `tenant` arg on `track()`. |
| **Feature names** | Short labels for the distinct AI-powered features/call sites (`"chat"`, `"summarize"`, `"onboarding-email"`). One per call site. | `feature` tag on AI calls; the `event` name on `track()`. |

**How to obtain them — infer, then confirm; block only if you can't infer:**

1. **Try to infer from the codebase.** The product line is often the repo
   name, `package.json`/`pyproject.toml` name, or app title. The tenant id is
   whatever the auth layer already exposes (`session.user.id`, `req.user.orgId`,
   `current_user.id`, `tenant_id` columns, etc.). Feature names follow from the
   function/route around each AI call.
2. **Propose your inferences and ask the developer to confirm or correct**,
   e.g.:
   > "I'll tag Surge with **product line `acme-chat`** (from package.json) and
   > use **`session.user.id`** as the customer identifier. For the two AI call
   > sites I found I'll use features **`chat`** and **`title-suggest`**. Are
   > these the names you want in the Surge dashboard, or should I change any?"
3. **If you cannot confidently infer a value — especially the tenant
   identifier — STOP and ask.** Do not proceed with a guessed or hardcoded
   tenant/customer value. Shipping `customer_id: "user"` or `tenant: "default"`
   silently destroys per-customer attribution and is worse than not integrating
   at all.

Do not continue to Step 1 until the product line and the tenant-identifier
scheme are settled. Feature names can be filled in per call site as you wire
them up.

---

## STEP 1 — Detect the stack and install

Determine the language and which AI provider SDK the app already uses (look for
`@anthropic-ai/sdk` / `anthropic`, `openai`, `@google/genai` / `google-genai`).

**Node / TypeScript:**
```bash
npm install affixly-surge-sdk
# the app should already depend on its provider SDK, e.g.:
#   npm install @anthropic-ai/sdk    # or  openai    or  @google/genai
```
Requires Node 18+ (uses global `fetch`).

**Python:**
```bash
pip install "affixly-surge-sdk[anthropic]"   # or [openai] / [gemini] / [all]
```
> PyPI name is `affixly-surge-sdk`; the **import name is `surge_sdk`**.

---

## STEP 2 — Configure once at startup

Put this in the app's entrypoint / server bootstrap, before any AI client is
constructed. **Never hardcode the API key or URL** — read them from the
environment. Add `SURGE_API_URL` and `SURGE_SDK_KEY` to the app's env/secrets;
tell the developer to generate the key at **Surge dashboard → Settings → SDK →
Generate API key**.

**Node:**
```ts
import { configure } from 'affixly-surge-sdk';

configure({
  surgeApiUrl: process.env.SURGE_API_URL!,
  surgeApiKey: process.env.SURGE_SDK_KEY!,
  productLine: 'acme-chat',            // ← the confirmed product line from Step 0
});
```

**Python:**
```python
import os
from surge_sdk import configure

configure(
    surge_api_url=os.environ["SURGE_API_URL"],
    surge_api_key=os.environ["SURGE_SDK_KEY"],
    product_line="acme-chat",          # ← the confirmed product line from Step 0
)
```

> Env-var fallback: `SURGE_API_URL`, `SURGE_SDK_KEY`, `SURGE_PRODUCT_LINE` are
> read automatically if you omit the corresponding config key.

---

## STEP 3 — Swap the client import (one line per client)

Change the provider import to the Surge-wrapped namespace. Everything else about
the client stays identical.

**Node — Anthropic:**
```ts
// - import Anthropic from '@anthropic-ai/sdk';
import { anthropic } from 'affixly-surge-sdk';
const client = new anthropic.Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
```
(`import { openai }` → `new openai.OpenAI(...)`; `import { gemini }` →
`new gemini.GoogleGenAI(...)`.)

**Python — Anthropic:**
```python
# - import anthropic
from surge_sdk import anthropic
client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
```
(`from surge_sdk import openai`; `from surge_sdk import gemini as genai`.)

At this point AI calls are already tracked under the product line. Steps 4–5
add the per-call attribution that makes the data useful.

---

## STEP 4 — Tag every AI call with feature + customer

For each call site, add `surgeTags` (Node) / `surge_tags` (Python) using the
**real tenant identifier** wired through from the request/session — never a
literal. These keys are stripped before the request reaches the provider.

**Node:**
```ts
const response = await client.messages.create({
  model: 'claude-sonnet-4-6',
  max_tokens: 1024,
  messages: [{ role: 'user', content: userInput }],
  surgeTags: {
    feature: 'chat',                 // ← this call site's feature name
    customer_id: session.user.id,    // ← the app's real, stable tenant id
  },
});
```

**Python:**
```python
response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    messages=[{"role": "user", "content": user_input}],
    surge_tags={
        "feature": "chat",                    # ← this call site's feature name
        "customer_id": str(current_user.id),  # ← the app's real, stable tenant id
    },
)
```

Streaming calls take the same tags — usage is captured as chunks flow and
reported when iteration finishes.

---

## STEP 5 (optional) — Record product events with `track()`

Use `track()` for non-AI product signals (activation, feature use, conversions)
keyed by the same tenant. `product` is filled from the configured product line.
The `tenant` argument must be the **same identifier scheme** you used for
`customer_id` in Step 4 — keep them consistent so spend and behavior join up.

**Node:**
```ts
import { track } from 'affixly-surge-sdk';
track('acme.thread.created', session.user.id, { channel: 'web' });
//     ^ event name          ^ real tenant id   ^ optional properties
```

**Python:**
```python
from surge_sdk import track
track(event="acme.thread.created", tenant=str(current_user.id),
      properties={"channel": "web"})
```

`track()` is fire-and-forget: returns immediately, never throws, silently drops
if Surge is unreachable or unconfigured.

---

## STEP 6 (optional) — Model overrides for plan tiering

If this app charges tiers, you can route models by tier without editing call
sites. Global map in `configure()` (`modelOverrides` / `model_overrides`), or
per-call `surgeModel` / `surge_model` (wins over the global map). Ask the
developer for the tier→model mapping before adding this — don't assume one.

---

## Guardrails — do NOT do these

- **Don't hardcode** the API key, `surgeApiUrl`, tenant ids, or customer ids.
  Keys/URLs come from env; tenant/customer ids come from the request context.
- **Don't invent** product-line, tenant, or feature values. If you're unsure of
  the tenant identifier, stop and ask (see Step 0).
- **Don't wrap** clients before `configure()` runs.
- **Don't block on Surge.** It's fire-and-forget by design; never `await` it in
  a way that gates the user response, and never add try/catch that changes app
  behavior on Surge failure.
- **Don't** reuse a single tag value across customers (e.g. `customer_id:
  'user'`). That collapses all attribution into one bucket.

## Rolling back

To untrack a call site, swap the import back to the real provider SDK. No other
changes needed:
```ts
import Anthropic from '@anthropic-ai/sdk';   // was: import { anthropic } from 'affixly-surge-sdk'
```

## Reference

- Node full guide: `docs/getting-started.md` in the `affixly-surge-sdk` (npm) package.
- Python full guide: `docs/getting-started.md` in the `affixly-surge-sdk` (PyPI, import `surge_sdk`) package.
- Event shape, streaming details, and operational guarantees are documented there.
