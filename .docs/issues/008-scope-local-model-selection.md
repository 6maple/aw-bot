# Issue 008: Add Scope-Local Model Selection

## Parent

.docs/prd/feishu-command-menu-card.md

## What to build

Add model listing and model selection as cross-Chat Bridge commands. A User can send `/model` to see available models and `/model use <model>` to select one for the current Private Chat Scope.

Model identifiers are represented as a single string in Bridge Core. Codex model options come from `CODEX_MODELS`, falling back to the configured `CODEX_MODEL` when no explicit list is configured. OpenCode model options come from the OpenCode provider/model API and are displayed as returned by that API using the single-string model identifier expected by the Bridge.

## Acceptance criteria

- [x] `/model` returns available models for the active Agent backend and identifies the current Private Chat Scope selection.
- [x] `/model use <model>` selects a model for the current Private Chat Scope only.
- [x] Missing model value fails fast with a clear error.
- [x] Unknown model values are rejected instead of silently accepted.
- [x] Codex model options come from `CODEX_MODELS`, with `CODEX_MODEL` as the only option when no list is configured.
- [x] OpenCode model options come from a fakeable provider/model API call in tests.
- [x] Tests use inert model names such as `test-model` or `test-provider/test-model` and make no real LLM/API calls.

## Blocked by

None - can start immediately.
