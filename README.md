# aw-bot

`aw-bot` is a personal Feishu bridge for local coding agents. It receives private chat messages, routes them into a local Agent Turn, streams progress back as a Run View, and pauses for user input or approval when the agent needs it.

The project is organized around a provider-neutral Bridge Core with concrete adapters for Feishu, Codex, and OpenCode.

## Status

This repository is an early personal workflow implementation. The architecture is intentionally optimized for one owner using one private chat scope, not for multi-user or group-chat operation.

## Core Ideas

- Private Feishu chat messages start or queue Agent Turns.
- A Run tracks one Agent Turn from input through streaming progress, pending requests, interruption, or completion.
- The Bridge Core owns domain behavior and exposes small ports.
- Adapters translate Feishu, Codex, OpenCode, persistence, and runtime details.
- Pending approval and user-input requests are routed back to the chat before the Run continues.
- Workspace changes clear the current Agent Session so hidden agent state does not cross project boundaries.

## Architecture

The dependency direction is:

```text
app -> adapters -> ports -> core
```

The Core uses provider-neutral terms such as Chat, Agent Session, Agent Turn, Run, Pending Request, Workspace, and Run View. Concrete systems stay behind adapters.

More design detail lives in:

- `.docs/CONTEXT.md`
- `.docs/architecture/bridge-core-detailed-design.md`
- `.docs/architecture/personal-workflow-behavior.md`
- `.docs/architecture/deferred-reference-bridge-capabilities.md`
- `.docs/adr/ADR-0001-bridge-core-ports-adapters.md`
- `.docs/adr/ADR-0002-accept-personal-workflow-behavior.md`

## Requirements

- Python 3.12.13 or newer
- `uv`
- Feishu bot credentials
- A local Codex or OpenCode endpoint, depending on the adapter you run

## Setup

Install dependencies:

```bash
uv sync
```

Create local environment files as needed:

```text
.env
.env.local
```

`.env.local` is ignored by git and should hold machine-local credentials and paths.

## Commands

Run startup validation:

```bash
uv run python -m c_auto_bridge.cli doctor
```

Start the bridge:

```bash
uv run python -m c_auto_bridge.cli start
```

## Tests

Run the test suite:

```bash
uv run python -m unittest discover -s tests
```

Tests must not make real LLM or provider API calls. Use fakes, mocks, and inert model names such as `test-model` or `test-provider/test-model`.

## Local Data

Runtime state is stored locally and is not committed:

- `.data/`
- `.cache/`
- `.env.local`

## Documentation

The `.docs` directory keeps only durable project context, architecture notes, PRDs, and accepted ADRs. Historical issue slices, handoff snapshots, and AI drafting notes are intentionally excluded from the public repository.
