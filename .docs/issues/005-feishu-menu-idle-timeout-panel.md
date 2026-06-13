# Issue 005: Configure Idle Timeout from the Menu

## Parent

.docs/prd/feishu-command-menu-card.md

## What to build

Add an Idle Timeout second-level panel. From the first-level command panel, the owner can choose common timeout settings without remembering `/timeout` arguments.

Each button should map to existing `/timeout` command behavior.

## Acceptance criteria

- [x] The first-level Idle Timeout button opens a second-level card.
- [x] The Idle Timeout card has fixed-value actions for 5, 10, and 30 minutes.
- [x] The fixed-value actions map to `/timeout 5`, `/timeout 10`, and `/timeout 30`.
- [x] The Idle Timeout card has an off action that maps to `/timeout off`.
- [x] The Idle Timeout card has a default action that maps to `/timeout default`.
- [x] Timeout actions from the menu preserve existing `/timeout` command semantics.
- [x] Tests use fakes or mocks and make no real Feishu, Codex, OpenCode, or LLM calls.

## Blocked by

.docs/issues/001-feishu-menu-entry-command-panel.md

.docs/issues/002-feishu-menu-direct-command-buttons.md
