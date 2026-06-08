# CLAUDE.md

## Project toolchain

- uv

## Rules

- Tests must never make real LLM/API calls. Use fakes or mocks for Codex/OpenCode/LLM clients, use inert model names such as `test-model` or `test-provider/test-model`, and do not put live provider/model IDs or real credentials in tests.

## Agent skills

### Issue tracker

Issues and PRDs are tracked as local Markdown files under `.scratch/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Uses the default five triage roles: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context domain docs live under `.docs/`: `.docs/CONTEXT.md` and `.docs/adr/`. See `docs/agents/domain.md`.
