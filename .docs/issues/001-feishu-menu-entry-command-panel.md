# Issue 001: Receive `aw_bot_menu()` and Send the First-Level Command Panel

## Parent

.docs/prd/feishu-command-menu-card.md

## What to build

Build the first end-to-end menu path for the Feishu Adapter. When the Feishu backend custom bot menu sends the exact event key `aw_bot_menu()`, the bot sends a deterministic first-level command panel to the menu operator by open_id. Follow the official Feishu menu event shape: the menu event includes `event_key` and `operator.operator_id`, but not Chat identity.

Opening the menu must not start an Agent Turn, must not call Codex or OpenCode, and must not call any LLM. The menu event is a Feishu Adapter input shape and should not introduce a Bridge Core menu concept.

## Acceptance criteria

- [x] The Feishu menu event with exact key `aw_bot_menu()` is normalized into an internal incoming menu event with User identity from `operator.operator_id.open_id`.
- [x] Runtime assembly wires the menu event callback alongside message and card action callbacks.
- [x] The Feishu Private Chat Adapter handles `aw_bot_menu()` by sending a first-level command panel card.
- [x] The first-level command panel includes entries for task actions, Workspace, historical Agent Sessions, Idle Timeout, and help.
- [x] Opening the command panel does not call Bridge Core text command handling.
- [x] Opening the command panel does not start an Agent Turn or call any Agent/LLM client.
- [x] Tests use fakes or mocks and make no real Feishu, Codex, OpenCode, or LLM calls.

## Blocked by

None - can start immediately.
