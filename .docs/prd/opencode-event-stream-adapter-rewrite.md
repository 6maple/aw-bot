# PRD: OpenCode Event Stream Adapter Rewrite

## Problem Statement

The current OpenCode Adapter no longer matches the current OpenCode Server API closely enough.

The Adapter mixes older event names and inferred behavior with the current server model. This makes Agent Turn ownership, output streaming, approval handling, and completion detection fragile. In particular, the Adapter must not treat a session-level event as enough proof that the current Agent Turn produced output or completed.

The Bridge Core already owns provider-neutral concepts such as Agent Session, Agent Turn, Run, Pending Request, and Run View. The OpenCode rewrite needs to keep OpenCode session, message, part, permission, and question details inside the Adapter boundary.

## Solution

Rewrite the OpenCode Adapter around the current OpenCode Server event stream.

The Adapter starts an Agent Turn with the asynchronous prompt API, then treats the Server event stream as the primary source of Run progress. It binds each Agent Turn to the user message ID submitted by the Bridge, then accepts only the assistant message whose parent ID matches that user message ID.

The Adapter translates OpenCode message part snapshots into Bridge Core Agent Events. It uses message read APIs only to backfill completion snapshots and recover final text that may not have been emitted before an idle event.

## User Stories

1. As the owner, I want OpenCode output to stream reliably into the Run View, so that I can follow progress from my private Chat.
2. As the owner, I want OpenCode approvals to pause the Run and wait for my explicit decision, so that tools do not proceed without consent.
3. As the owner, I want OpenCode completion to apply only to the current Agent Turn, so that old or unrelated session events do not complete the wrong Run.
4. As the owner, I want unsupported OpenCode interactive requests to fail clearly, so that the Run does not hang silently.
5. As a maintainer, I want the OpenCode Adapter to use official Server capabilities, so that future API drift is visible at startup or in focused Adapter tests.

## Implementation Decisions

Use the current OpenCode Server API as the Adapter contract. The required capabilities are:

- server health check
- event stream
- create session
- asynchronous prompt
- message read
- permission reply
- abort session

Optional capabilities are:

- question request and reply
- runtime agent listing
- runtime provider and model listing

The event stream is the only real-time output source. Global event streams are not used for Agent Turn progress.

Starting an Agent Turn:

- The Adapter generates a user message ID for the prompt.
- The Adapter submits the prompt asynchronously with the configured model and agent when present.
- The prompt call returning successfully means only that the turn was accepted, not that output has started.

Turn ownership:

- The generated user message ID is the root of the Agent Turn.
- The Adapter binds the turn to the assistant message whose parent ID equals that user message ID.
- User prompt echo, old assistant output, and unrelated same-session messages are ignored for the active Run.

Part streaming:

- Message part updates are snapshot events.
- The Adapter stores prior text per part ID and computes deltas itself.
- Text parts become `TextDelta`.
- Reasoning or thinking parts become `ThinkingDelta`.
- Tool parts become `ToolStarted` and `ToolFinished` only after the official part state is understood from the local OpenCode schema and locked by tests.

Completion:

- Session idle or status idle is a soft completion signal.
- The Adapter emits `RunCompleted` only after the current assistant message is known or found through message backfill.
- Backfill reads only the current session and only the smallest practical message scope. It does not scan full historical session state.

Permission:

- Approval decisions support only per-request decisions in the first rewrite.
- `accept`, `approve`, and `allow` map to OpenCode `once`.
- `reject`, `deny`, and `abort` map to OpenCode `reject`.
- The Adapter does not implement remember, always, or Codex-like automatic approval.

Question and user input:

- Question support is enabled only if the local OpenCode API schema explicitly exposes question request events and reply endpoints.
- If enabled, only a single question that can be answered accurately with one string is supported.
- Multi-question requests and complex structured forms fail fast.
- If question capability is absent, the Adapter does not register question translation. A question-like event for the active turn is logged and fails the Run.

Unknown events:

- Events unrelated to the active turn are ignored with debug logging.
- Unknown events that belong to the active session or active turn are logged with structured context.
- Unknown interactive events for the active turn fail the Run instead of being silently ignored.

SSE lifecycle:

- The first rewrite does not implement event replay or cursor-based recovery.
- If the event stream disconnects, active Runs fail with a clear event-stream interruption error.
- Replay can be added later only if the official API exposes cursor or replay semantics.

Startup checks:

- Required capabilities fail startup when missing.
- Optional capabilities are detected and recorded.
- If an OpenCode agent override is configured and an agent listing API is available, the Adapter validates the configured agent at startup.
- Provider and model validation uses the current official runtime provider API when available; otherwise it can retain the existing provider configuration check as a startup-only compatibility check.

## Testing Decisions

Highest practical test seams:

- HTTP client contract tests for required OpenCode endpoints and request bodies.
- SSE parser tests for event-stream framing, JSON data payloads, and stream termination.
- OpenCode event translator tests using current official event payloads.
- Turn router tests for user message ID to assistant parent ID binding.
- Snapshot delta tests for text and reasoning parts.
- Completion tests for idle before output, idle after output, and completion backfill.
- Permission tests for `once` and `reject` mapping.
- Question capability tests for absent question support, supported single-question reply, and unsupported multi-question failure.
- Unknown event logging tests for ignored events, active-turn warnings, and active-turn interactive failure.
- Runtime wiring tests that ensure the OpenCode event listener reports stream interruption to active Runs.

Tests must use fakes or mocks for OpenCode. They must not make real OpenCode, LLM, or provider calls.

## Out of Scope

- Supporting old OpenCode event names as the main path.
- Using global event streams for Agent Turn progress.
- Codex-like automatic approval.
- Remember or always permission decisions.
- Multi-question or structured question forms.
- Event replay or disconnect recovery without official cursor or replay support.
- Changing Bridge Core vocabulary or leaking OpenCode message and part records into Core.
- Adding new third-party dependencies for the Adapter rewrite.

## Further Notes

The confirmed design is based on the current OpenCode Server documentation and the local project decision to keep Bridge Core provider-neutral.

The local OpenCode server schema remains the final authority for exact endpoint names and event payload shapes. The rewrite should use that schema to lock down tool part and question behavior before implementation.

Relevant project decisions:

- ADR-0001: Use Bridge Core with Ports and Adapters

The next step is issue slicing for a small set of vertical implementation issues.
