# Issue 002: Map First-Level Menu Command Buttons to Existing Text Commands

## Parent

.docs/prd/feishu-command-menu-card.md

## What to build

Add direct command buttons to the first-level command panel. Menu card actions should use a `menu:` action prefix and map safe direct actions to existing private Chat text commands.

The behavior of `/stop`, `/new`, and `/reset` must remain the same whether invoked by text or by a menu button. Existing Run View card actions such as stop, approve, and reject must continue to work unchanged.

## Acceptance criteria

- [x] Menu card actions use a `menu:` command prefix and do not collide with existing Run View actions.
- [x] The menu stop button maps to the same behavior as `/stop`.
- [x] The menu new task button maps to the same behavior as `/new`.
- [x] The menu reset button maps to the same behavior as `/reset`.
- [x] Direct menu command execution reuses existing Bridge Core private Chat text command handling.
- [x] Existing Run View stop, approve, and reject actions still pass regression tests.
- [x] Tests prove menu command buttons do not call any Agent/LLM client except through the existing command behavior they invoke.

## Blocked by

.docs/issues/001-feishu-menu-entry-command-panel.md
