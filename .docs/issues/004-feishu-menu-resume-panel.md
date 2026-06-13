# Issue 004: Show Historical Agent Sessions and Resume from the Menu

## Parent

.docs/prd/feishu-command-menu-card.md

## What to build

Add a historical Agent Session second-level panel. From the first-level command panel, the owner can open a list of compatible historical Agent Sessions and resume one without copying a session id.

Resuming from the card should map to existing `/resume <session_id>` behavior. Compatibility rules should match the existing `/resume` behavior for Agent, Workspace, and Access Mode.

## Acceptance criteria

- [x] The first-level historical Agent Session button opens a second-level card.
- [x] The card lists compatible historical Agent Sessions using existing resume compatibility behavior.
- [x] Each historical Agent Session item shows useful identifying details, including session identity, Workspace, Agent, and update time.
- [x] Each listed session has a resume action that maps to `/resume <session_id>`.
- [x] The card has an empty state when there are no compatible historical Agent Sessions.
- [x] Resume from the menu preserves existing `/resume <session_id>` command semantics.
- [x] Tests use fakes or mocks and make no real Feishu, Codex, OpenCode, or LLM calls.

## Blocked by

.docs/issues/001-feishu-menu-entry-command-panel.md

.docs/issues/002-feishu-menu-direct-command-buttons.md
