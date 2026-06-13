# Issue 009: Pass the Selected Model into Agent Turns

## Parent

.docs/prd/feishu-command-menu-card.md

## What to build

Make the Private Chat Scope's selected model affect subsequent Agent Turns. The selected model should be passed from Bridge Core into the active Agent Adapter when a new Agent Turn starts.

Codex should receive the selected model string directly. OpenCode should receive the same selected string from Bridge Core and translate it into its prompt payload at the OpenCode Adapter boundary.

Changing the selected model must not change an already-active Run.

## Acceptance criteria

- [x] New Codex Agent Turns use the current Private Chat Scope selected model.
- [x] New OpenCode Agent Turns use the current Private Chat Scope selected model.
- [x] OpenCode model payload translation remains inside the OpenCode Adapter boundary.
- [x] Changing the selected model does not mutate an active Run.
- [x] If model switching needs a fresh Agent Session, the current Private Chat Scope session selection is cleared for subsequent turns.
- [x] Tests use fakes or mocks and make no real Codex, OpenCode, Feishu, or LLM calls.

## Blocked by

.docs/issues/008-scope-local-model-selection.md
