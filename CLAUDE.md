# CLAUDE.md

## Project toolchain

- uv

## Rules

- Tests must never make real LLM/API calls. Use fakes or mocks for Codex/OpenCode/LLM clients, use inert model names such as `test-model` or `test-provider/test-model`, and do not put live provider/model IDs or real credentials in tests.
