# Issue 011: Add OpenCode Plan/Build Switching

## Parent

.docs/prd/feishu-command-menu-card.md

## What to build

Add OpenCode-only switching between the `plan` and `build` OpenCode agents for the current Private Chat Scope. A User can select `/agent plan` or `/agent build`, and that selection affects subsequent OpenCode Agent Turns in that scope.

This command is not available for non-OpenCode runtimes.

## Acceptance criteria

- [x] `/agent plan` selects the OpenCode `plan` agent for the current Private Chat Scope.
- [x] `/agent build` selects the OpenCode `build` agent for the current Private Chat Scope.
- [x] Any other `/agent` value fails fast with a clear error.
- [x] Non-OpenCode runtimes reject `/agent plan` and `/agent build` clearly.
- [x] The selected OpenCode agent affects subsequent OpenCode Agent Turns only.
- [x] Changing the selected OpenCode agent does not mutate an active Run.
- [x] Tests use fakes or mocks and make no real OpenCode, Feishu, or LLM calls.

## Blocked by

None - can start immediately.
