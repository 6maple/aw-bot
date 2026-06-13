# Issue 007: Add a Cross-Chat File Finder Command

## Parent

.docs/prd/feishu-command-menu-card.md

## What to build

Add a cross-Chat file finder command for the current Workspace. When a User sends `/files <query>`, the Bridge returns up to 10 matching file paths whose Workspace-relative path contains the query.

This is a file path finder, not full-text search. It must avoid noisy project/runtime directories and must not start an Agent Turn or call Codex, OpenCode, Feishu, or any LLM client.

## Acceptance criteria

- [x] `/files <query>` searches the current Workspace for matching file paths and returns at most 10 results.
- [x] Missing or blank query fails fast with a clear error.
- [x] Results are Workspace-relative paths.
- [x] The search excludes `.git`, `.venv`, `node_modules`, `.data`, and `.cache`.
- [x] The command is available through Bridge Core so every Chat Adapter can use it.
- [x] The command does not start an Agent Turn.
- [x] Tests use fakes or local temporary files and make no real Codex, OpenCode, Feishu, or LLM calls.

## Blocked by

None - can start immediately.
