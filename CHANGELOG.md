# Changelog

All notable changes to `affixly-surge-sdk` are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/), and the project
follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed
- `from surge_sdk import anthropic` no longer fails on `anthropic` 1.x.
  `HUMAN_PROMPT` / `AI_PROMPT` (legacy Text Completions constants, removed in
  anthropic 1.x) are now re-exported only when the installed `anthropic`
  provides them, so the wrapper imports on both 0.x and 1.x.
- `track_quota_event()` now sends the event's top-level `product` as the
  `product_line` argument when one is given, instead of always using the
  `product_line` from `configure()`. Falls back to the configured value when
  `product_line` is `None`.

## [0.7.0] — 2026-10-01

### Added
- `plan` usage tag — pass it in `surge_tags` per call or in
  `configure(default_tags=...)`; forwarded as the event's `plan` field for
  per-plan cost attribution.
- `track_quota_event(kind, product_line, customer_id, plan=None, **fields)` —
  helper over `track()` that posts `quota.ceiling_hit` / `quota.limit_hit`
  events scoped to a customer.
- `flush(timeout=None) -> bool` — block until outstanding reports are sent (or
  `timeout` elapses); for short-lived scripts and serverless where the `atexit`
  drain may not run.
- `set_diagnostics(on_report_error=None)` — opt-in observation of dropped
  reports. Never changes failure behavior; Surge still never raises.
- `X-Surge-Quota: exceeded` handling — the SDK warns once per process (never
  raises) when the backend reports the event quota is exhausted; events are
  dropped server-side.
- Docs: capability matrix (now including OpenAI audio transcription), failure
  semantics (provider-call vs reporting failure), process lifecycle, and
  compatibility & versioning sections.

### Changed
- `__version__` is now read from installed package metadata
  (`importlib.metadata`), single-sourced from `pyproject.toml` at build — no
  hand-maintained duplicate.

### Fixed
- `AGENTS.md` rollback guidance: reverting to the bare provider SDK also
  requires removing the Surge-only `surge_tags` / `surge_model` kwargs, and the
  example is now Python (was an incorrect TypeScript snippet).

## [0.6.0]

### Added
- `track()` for arbitrary product-event reporting, keyed by tenant.

## [0.5.0]

### Added
- OpenAI audio transcription tracking (`audio.transcriptions.create()`), billed
  per audio-minute.
