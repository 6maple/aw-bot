# Bridge Core Detailed Design

## Status

Accepted

## Goal

Refactor `c_auto_bridge` around a provider-neutral Bridge Core. The architecture must keep domain behavior local, expose small Interfaces, and isolate external systems behind Adapters.

Compatibility with existing module paths, field names, and persisted data is not a design constraint.

The functional semantics should align with the personal workflow in `lark-coding-agent-bridge`, while the Agent scope remains Codex and OpenCode.

The accepted personal workflow baseline is:

- private Chat message starts a queued or merged Run
- streaming Run View card
- `/new` or `/reset`
- `/stop`
- `/cd <path>`
- `/ws list`, `/ws save`, `/ws use`, `/ws remove`
- `/resume`
- `/status`
- image and file attachments cached locally and passed to the Agent
- idle timeout watchdog
- Pending Request handling for approval and user input
- structured local Run logs

The current Chat Scope model is a single owner Private Chat Scope. Group chat and topic scope are not modeled in the Core baseline.

Changing Workspace with `/cd` or `/ws use` interrupts the active Run and clears the current Agent Session.

Detailed Personal Bridge behavior is defined in `personal-workflow-behavior.md`.

## Dependency Rule

Dependencies point inward.

```text
app -> adapters -> ports -> core
```

`core` owns domain language and behavior. `ports` owns Interfaces required by `core`. `adapters` implement Ports for concrete systems. `app` wires concrete implementations together.

No Core Module imports Feishu, Codex, OpenCode, filesystem storage, CLI, process, HTTP, or JSON-RPC clients.

## Package Layout

```text
c_auto_bridge/
  core/
    agent_events.py
    agent_session.py
    attachments.py
    clock.py
    pending_request.py
    queue.py
    run.py
    run_controller.py
    run_reducer.py
    run_view.py
    workspace.py
    use_cases.py
  ports/
    agent.py
    chat.py
    persistence.py
    run_view_sink.py
  adapters/
    agent_codex/
      adapter.py
      event_router.py
      translator.py
      jsonrpc_client.py
    agent_opencode/
      adapter.py
      event_router.py
      translator.py
      http_client.py
      server_process.py
    chat_feishu/
      gateway.py
      message.py
      stream_card_sink.py
      card_renderer.py
      text_renderer.py
    persistence_file/
      file_store.py
      records.py
  app/
    config.py
    runtime.py
    cli.py
    startup_checks.py
  utils/
    atomic_file.py
    ids.py
    log.py
```

## Core Modules

### `core.agent_session`

Owns provider-neutral identity records.

Core terms:

- `AgentSessionId`
- `AgentTurnId`
- `AgentName`
- `AgentSession`

It does not contain provider field names such as `codex_thread_id` or Feishu owner names. Provider-specific IDs are stored as opaque Agent Session IDs.

### `core.agent_events`

Owns the event vocabulary that all Agent Adapters translate into.

Examples:

- `TextDelta`
- `ThinkingDelta`
- `ToolStarted`
- `ToolFinished`
- `UserInputRequested`
- `ApprovalRequested`
- `UsageUpdated`
- terminal Run events

This Module has high Depth because Adapters can vary while Core orchestration stays unchanged.

### `core.run`

Owns `Run`, `RunId`, `RunStatus`, and the link from a Run to an Agent Session and Agent Turn.

The Run record should not know how it is displayed or persisted. It is the durable Core state for one Agent Turn.

### `core.pending_request`

Owns `PendingRequest`, `PendingRequestId`, `PendingKind`, and `PendingStatus`.

Pending Request is provider-neutral. Adapter request payloads may be kept as opaque data only when the answering Adapter needs them.

### `core.run_reducer`

Pure state transition Module.

Input: current Run state and one Agent Event.  
Output: next Run state.

It must not persist, render, send messages, create tasks, call Agents, or inspect Adapter-specific payloads.

### `core.run_view`

Owns provider-neutral user-facing Run View state.

This replaces the current `react` name. The term is about Bridge output, not a frontend framework.

### `core.run_controller`

Owns orchestration for one active Run:

- create or reuse Agent Session
- start Agent Turn
- consume Agent Events
- apply reducer
- open and close Pending Requests
- stop, interrupt, timeout, and fail Runs
- publish Run View updates through a Port

It does not know Feishu cards, Codex JSON-RPC, OpenCode HTTP, or file paths.

### `core.use_cases`

Owns Chat-facing commands as use cases:

- handle Chat message
- handle Run View action
- answer Pending Request
- stop Run

This replaces the current `bot.command_router` role. It speaks Core terms and delegates execution to `RunController`.

## Ports

Ports are Interfaces owned by the Bridge Core.

### `ports.agent`

Required behavior:

- create Agent Session
- start Agent Turn
- stream Agent Events for a Turn
- stop Turn
- answer User Input
- answer Approval

The Port uses Core IDs, Core events, Attachments, Workspace, and Access Mode only. Codex thread IDs and OpenCode session IDs are Adapter internals.

### `ports.chat`

Required behavior:

- receive Chat messages
- receive Run View actions
- send plain text when a richer Run View is unavailable

Inbound transport details are Adapter internals.

### `ports.persistence`

Required behavior:

- save and load Agent Sessions
- save and load Runs
- save and query Pending Requests
- append Run Events and errors
- recover incomplete Runs at startup

The Port should be split into narrow Protocols when Core callers only need part of it. For example, `RunRepository`, `PendingRepository`, and `AgentSessionRepository` reduce coupling without forcing separate concrete stores.

### `ports.run_view_sink`

Required behavior:

- create Run View
- update Run View
- mark final state
- fall back to text output when no rich view exists

Feishu StreamCard is one Adapter for this Port, not a Core concept.

## Adapters

The current Agent Adapters are Codex and OpenCode. Claude is not part of the accepted scope. Adding Claude later should require a new Agent Adapter, not Core changes.

### Codex Agent Adapter

Translates Codex JSON-RPC protocol into `ports.agent`.

Local responsibilities:

- JSON-RPC connection lifecycle
- Codex request and response shapes
- Codex event routing
- Codex event translation
- Codex approval decision mapping

It must not persist Core records directly unless persistence is explicitly part of the Port call made by Core.

### OpenCode Agent Adapter

Translates OpenCode Server protocol into `ports.agent`.

Local responsibilities:

- HTTP client calls
- OpenCode event stream
- OpenCode event routing
- OpenCode event translation
- OpenCode permission decision mapping
- optional local server process management

OpenCode should not reuse Codex field names.

### Feishu Chat Adapter

Translates Feishu messages and card actions into Core use cases.

Local responsibilities:

- Feishu SDK gateway
- inbound message parsing
- card action parsing
- StreamCard transport
- card rendering
- plain text fallback delivery

It must not decide Run state transitions.

### File Persistence Adapter

Implements persistence Ports with local files.

Local responsibilities:

- directory layout
- atomic writes
- JSON serialization
- indexes
- recovery mutation

Serialization records may differ from Core dataclasses if that keeps storage concerns out of Core.

## App Layer

The app layer is the composition root.

Responsibilities:

- load environment and config
- validate startup requirements
- choose concrete Agent Adapter
- choose concrete Chat Adapter
- choose concrete Persistence Adapter
- wire Ports into Core use cases
- start and stop runtime loops

`app.runtime` should not contain protocol translation, Run state changes, persistence rules, or rendering decisions.

## Interaction Flow

### Chat Message to Run

```text
Feishu Gateway
  -> Feishu Chat Adapter
  -> Core use case: handle Chat message
  -> RunController
  -> Agent Port
  -> Codex/OpenCode Agent Adapter
```

The use case first checks for an open Pending Request for the owner. If one exists, the message answers it. Otherwise the message starts or queues a Run for the Private Chat Scope.

Workspace-changing commands are handled before normal queued Run creation because they invalidate the active Agent Session.

### Agent Event to Run View

```text
Agent Adapter
  -> Agent Event
  -> RunController
  -> Run Reducer
  -> Persistence Port
  -> Run View Sink Port
  -> Feishu StreamCard Adapter
```

Only the Adapter knows the provider event shape. Only the reducer knows state transition rules. Only the Run View Sink knows how to display state.

### Run View Action to Agent

```text
Feishu Card Action
  -> Feishu Chat Adapter
  -> Core use case: handle Run View action
  -> RunController
  -> Agent Port answer or stop
```

The action payload is parsed at the Feishu boundary. Core receives a provider-neutral command such as stop Run, accept Pending Request, or deny Pending Request.

## Coupling Controls

Core dataclasses use Core vocabulary only.

Adapter payloads do not leak into Core except as opaque Pending Request context needed to answer that same request.

Ports are defined from Core needs, not from external API shapes.

Concrete Adapters are only constructed in `app`.

Use cases depend on narrow persistence Interfaces instead of a broad Store when possible.

Rendering receives Run View state and returns transport-specific output. Rendering does not query persistence or mutate Runs.

Runtime lifecycle is separate from domain lifecycle. Threads, futures, process management, and sockets live in `app` or Adapters.

## Deletion Tests

Deleting `adapters.agent_codex` must not affect Core, Feishu, OpenCode, or file persistence behavior.

Deleting `adapters.chat_feishu` must not affect Core or Agent Adapters.

Deleting `adapters.persistence_file` must only require another Persistence Adapter.

Deleting `core.run_controller` should spread orchestration complexity to many callers; therefore it is a deep Module and should remain.

Deleting `core.run_reducer` should force state transition rules into orchestration and renderers; therefore it is a deep Module and should remain.

## Naming Decisions

Use `Chat` instead of Feishu chat in Core.

Use `Private Chat Scope` for the current Personal Bridge scope model.

Use `User` instead of Feishu user in Core.

Use `Agent Session` instead of Codex thread or OpenCode session in Core.

Use `Agent Turn` instead of Codex turn or OpenCode message in Core.

Use `Run View` instead of StreamCard in Core.

Use `Pending Request` instead of approval card or question in Core.

Use `Workspace` instead of cwd in Core-facing names.

## Non-Goals

This design does not preserve existing import paths.

This design does not preserve existing persisted JSON field names.

This design does not define implementation sequencing.

This design does not introduce new dependencies.

This design does not add Claude support.

Deferred reference-bridge capabilities are archived in `deferred-reference-bridge-capabilities.md`.
