# Issue 012: Expand the Feishu Command Panel for Common Agent Actions

## Parent

.docs/prd/feishu-command-menu-card.md

## What to build

Expand the Feishu command panel with entries for skills, model selection, file search, and OpenCode plan/build switching. Card actions should route through shared text commands so the behavior stays available to every Chat Adapter.

The plan/build entry must be shown only when the runtime's active Agent backend is OpenCode. Codex and other non-OpenCode runtimes must not show plan/build controls.

## Acceptance criteria

- [x] The first-level command panel includes entries for skills, model selection, and file search.
- [x] OpenCode runtimes include a plan/build switching entry.
- [x] Non-OpenCode runtimes do not include a plan/build switching entry.
- [x] Skills panel actions route through `/skills`.
- [x] Model panel actions route through `/model` and `/model use <model>`.
- [x] File search actions route through `/files <query>` or provide a deterministic prompt/template for the User to send that command.
- [x] OpenCode plan/build buttons route through `/agent plan` and `/agent build`.
- [x] Opening or navigating menu panels does not start an Agent Turn or call an LLM client.
- [x] Tests use fakes or mocks and make no real Feishu, Codex, OpenCode, or LLM calls.

## Blocked by

.docs/issues/007-cross-chat-file-finder-command.md

.docs/issues/008-scope-local-model-selection.md

.docs/issues/010-agent-specific-skills-listing.md

.docs/issues/011-opencode-plan-build-switch.md
