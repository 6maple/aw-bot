# Issue 003: Show Saved Workspaces and Use a Workspace from the Menu

## Parent

.docs/prd/feishu-command-menu-card.md

## What to build

Add a Workspace second-level panel. From the first-level command panel, the owner can open a saved Workspace list. The list shows saved Workspaces and lets the owner choose one without typing its name.

Using a Workspace from the card should map to the existing `/ws use <name>` behavior, including the existing rule that changing Workspace clears the current Agent Session and may interrupt an active Run.

## Acceptance criteria

- [x] The first-level Workspace button opens a Workspace second-level card.
- [x] The Workspace card lists saved Workspaces using existing persistence behavior.
- [x] Each saved Workspace item shows its name, path, and update time.
- [x] Each saved Workspace item has a use action that maps to `/ws use <name>`.
- [x] The Workspace card has an empty state when no saved Workspaces exist.
- [x] Workspace use from the menu preserves existing `/ws use` command semantics.
- [x] Workspace delete, `/cd <path>`, and `/ws save <name>` are not implemented in this slice.
- [x] Tests use fakes or mocks and make no real Feishu, Codex, OpenCode, or LLM calls.

## Blocked by

.docs/issues/001-feishu-menu-entry-command-panel.md

.docs/issues/002-feishu-menu-direct-command-buttons.md
