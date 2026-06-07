# PRD: Personal Bridge Core Refactor

## Problem Statement

`c_auto_bridge` needs a large architecture cleanup so it can stay maintainable as a Personal Bridge.

The current code mixes Bridge Core behavior with Feishu, Codex, OpenCode, storage, and runtime assembly details. Provider-specific names leak into shared records, and orchestration Modules carry responsibilities for Agent execution, persistence, Run View updates, Pending Requests, and external transport behavior at the same time.

The product direction is now explicit:

- align personal workflow semantics with `lark-coding-agent-bridge`
- support one owner using one Private Chat Scope
- keep Agent scope to Codex and OpenCode
- prioritize architecture cleanliness over compatibility with existing module paths, field names, and persisted data

## Solution

Refactor the project into a Core-first Personal Bridge architecture.

The dependency rule is:

```text
app -> adapters -> ports -> core
```

Bridge Core owns provider-neutral behavior and vocabulary. Ports define Core-required Interfaces. Adapters implement Ports for concrete systems. App is the composition root.

The Personal Bridge behavior baseline includes:

- private Chat message starts a queued or merged Run
- one streaming Run View card
- `/new` and `/reset`
- `/stop`
- `/cd <path>`
- `/ws list`, `/ws save`, `/ws use`, `/ws remove`
- `/resume`
- `/status`
- image and file Attachments cached locally and passed to the Agent
- Idle Timeout watchdog, disabled by default
- Pending Requests for approval and user input
- structured local Run logs

## User Stories

1. As the owner, I want to message the bot in my private Chat, so that it starts an Agent Turn in the current Workspace.
2. As the owner, I want Run output to stream into one Run View card, so that text, thinking, tool calls, pending state, and terminal state stay readable.
3. As the owner, I want messages sent during an active Run to queue and merge, so that follow-up input becomes the next Agent Turn instead of colliding with the current one.
4. As the owner, I want `/stop` to interrupt the active Run, so that I can regain control immediately.
5. As the owner, I want `/new` or `/reset` to interrupt the active Run and clear the current Agent Session while keeping the Workspace, so that I can start fresh in the same project.
6. As the owner, I want `/cd` and `/ws use` to switch Workspace and clear the current Agent Session, so that hidden Agent state does not cross project boundaries.
7. As the owner, I want `/resume` to restore a compatible historical Agent Session, so that I can continue useful context without mixing incompatible Agent, Workspace, or Access Mode state.
8. As the owner, I want image and file Attachments passed to the Agent, so that local coding tasks can include external inputs from Chat.
9. As the owner, I want Pending Requests to pause the Run and accept my next answer or card decision, so that approval and user-input flows work without starting unrelated Runs.
10. As the owner, I want structured local logs, so that I can diagnose startup, Run events, and errors without telemetry.

## Implementation Decisions

Use the accepted Core-first package shape:

```text
c_auto_bridge/
  core/
  ports/
  adapters/
  app/
  utils/
```

Core Modules:

- `core.agent_events` owns provider-neutral Agent Event vocabulary.
- `core.agent_session` owns Agent Session and Agent Turn identity records.
- `core.run` owns Run records and status.
- `core.pending_request` owns Pending Request records and status.
- `core.run_reducer` owns pure Run state transitions.
- `core.run_view` owns provider-neutral Run View state.
- `core.queue` owns Queued Message and Message Merge Window behavior.
- `core.workspace` owns Workspace selection and validation rules.
- `core.attachments` owns accepted Attachment metadata and policy.
- `core.run_controller` owns active Run orchestration.
- `core.use_cases` owns Chat-facing commands and Run View actions.

Ports:

- `ports.agent` creates Agent Sessions, starts Agent Turns, streams Agent Events, stops Turns, and answers Pending Requests.
- `ports.persistence` saves and loads Agent Sessions, Runs, Pending Requests, Workspaces, Attachments, and Run logs. Use narrow Protocols where Core callers need only part of persistence.
- `ports.run_view_sink` creates and updates Run Views and falls back to text.
- `ports.chat` receives Chat messages and Run View actions.

Adapters:

- Codex Adapter translates Codex JSON-RPC into the Agent Port.
- OpenCode Adapter translates OpenCode Server behavior into the Agent Port.
- Feishu Adapter translates private Chat messages and card actions into Core use cases and renders Run View cards.
- File Persistence Adapter implements local JSON/JSONL storage.

Core vocabulary must not include Feishu, Codex, or OpenCode field names. Use `Private Chat Scope`, `User`, `Agent Session`, `Agent Turn`, `Run`, `Pending Request`, `Run View`, `Workspace`, `Attachment`, `Idle Timeout`, and `Access Mode`.

Message Queue decisions:

- ordinary messages during an active Run become Queued Messages
- Queued Messages merge for 1.5 seconds into the next prompt
- `/stop`, `/new`, `/reset`, `/cd`, and `/ws use` bypass the queue

Workspace decisions:

- Workspace inputs must be absolute paths or `~/...`
- Workspaces must resolve to existing directories
- filesystem root, home root, system directories, and temporary directory roots are rejected
- `/cd` and `/ws use` interrupt active Run and clear current Agent Session

Session decisions:

- `/new` and `/reset` interrupt active Run, clear current Agent Session, and preserve Workspace
- `/resume` requires same Agent, same Workspace, and compatible Access Mode

Attachment decisions:

- support image and file Attachments
- cache Attachments locally before passing them to the Agent
- do not immediately delete cached Attachments after Run completion
- audio, video, and stickers remain deferred

Run View decisions:

- use one streaming card
- Core emits provider-neutral Run View state
- Feishu Adapter renders cards
- rendering must not query persistence or mutate Run state

Idle Timeout decisions:

- supported but disabled by default
- support global value and Private Chat Scope override with `/timeout [N|off|default]`
- timeout interrupts the Run and produces terminal Run View state

Access Mode decisions:

- one global owner-selected Access Mode: `full`, `workspace`, or `read-only`
- map Access Mode inside Codex and OpenCode Adapters
- do not implement user-level access policy

App decisions:

- support foreground `start` and `doctor`
- app layer loads config, validates startup, chooses Adapters, wires Ports, and owns runtime lifecycle
- no daemon, service manager, process registry, `/ps`, or `/exit`

## Testing Decisions

Highest practical test seams:

- `core.run_reducer`: pure Agent Event to Run View state transitions.
- `core.queue`: active Run queueing, 1.5 second merge behavior, interrupting command bypass.
- `core.workspace`: path expansion and rejection of unsafe directories.
- `core.use_cases`: command routing for normal messages, Pending Requests, `/new`, `/stop`, `/cd`, `/ws`, `/resume`, `/status`, and `/timeout`.
- `core.run_controller`: active Run lifecycle with fake Agent Port, fake persistence, and fake Run View Sink.
- Codex Adapter translator/router: provider events to Core Agent Events and Pending Request answers.
- OpenCode Adapter translator/router: provider events to Core Agent Events and Pending Request answers.
- Feishu Adapter parser/renderer: private Chat message normalization, card action parsing, and Run View card rendering.
- File Persistence Adapter: JSON records, JSONL logs, recovery of incomplete Runs and Pending Requests.
- App composition: selected Agent Adapter, startup checks, and foreground lifecycle.

Tests should prefer Core-level unit tests and Adapter contract tests. End-to-end tests should use fake Ports and avoid real Feishu, Codex, or OpenCode dependencies unless explicitly testing an Adapter boundary.

## Out of Scope

- Claude support
- group chat
- topic scope
- invite/remove/admin/access policy
- multi-profile product management
- daemon or service management
- process registry commands
- cloud document comments
- multi-user `lark-cli` identity policy
- telemetry plugins
- audio, video, and sticker Attachments
- preserving existing import paths
- preserving existing persisted JSON field names

## Further Notes

Accepted architecture documents:

- `bridge-core-detailed-design.md`
- `personal-workflow-behavior.md`
- `deferred-reference-bridge-capabilities.md`

Accepted ADRs:

- ADR-0001: Use Bridge Core with Ports and Adapters
- ADR-0002: Accept Personal Workflow Behavior

The next step is issue slicing. Issues should be vertical enough to verify behavior, but ordered so Core contracts stabilize before Adapter rewrites.
