# Issue 010: Add Agent-Specific Skills Listing

## Parent

.docs/prd/feishu-command-menu-card.md

## What to build

Add `/skills` as a cross-Chat command that lists skills from the active Agent backend. The Bridge must use the backend's official/API-backed skill listing instead of scanning directories itself.

Codex should use the Codex app-server skills listing capability. OpenCode should use the OpenCode skills API and display what that API returns. The command must not mix Codex skills into an OpenCode runtime, or OpenCode skills into a Codex runtime.

## Acceptance criteria

- [x] `/skills` is available through Bridge Core so every Chat Adapter can use it.
- [x] Codex skills are fetched through a fakeable Codex app-server skills listing call.
- [x] OpenCode skills are fetched through a fakeable OpenCode skills API call.
- [x] The result display includes each returned skill name and description when present.
- [x] The Bridge does not scan skill directories as a fallback.
- [x] The Bridge does not return skills from a different Agent backend.
- [x] Tests use fakes or mocks and make no real Codex, OpenCode, Feishu, or LLM calls.

## Blocked by

None - can start immediately.
