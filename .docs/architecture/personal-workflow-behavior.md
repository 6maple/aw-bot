# Personal Workflow Behavior

## Status

Accepted.

## Purpose

This document defines the accepted Personal Bridge behavior for `aw-bot`. It complements the Core-first architecture design by fixing user-visible semantics before implementation.

## Queue Semantics

While a Run is active, ordinary Chat messages become Queued Messages.

Queued Messages received during the Message Merge Window are combined into one prompt for the next Agent Turn.

If a Queued Message includes supported Attachments, those Attachments are preserved and passed to the next Agent Turn with the merged prompt.

Interrupting commands bypass the queue:

- `/stop`
- `/new`
- `/reset`
- `/cd <path>`
- `/ws use <name>`

## Message Merge Window

The Message Merge Window is fixed at 1.5 seconds.

It is not configurable in the Personal Bridge baseline.

## `/new` and `/reset`

`/new` and `/reset` interrupt the active Run, clear the current Agent Session, and keep the current Workspace.

## `/resume`

`/resume` restores only a compatible historical Agent Session.

Compatibility requires:

- same Agent
- same Workspace
- compatible Access Mode

## Workspace Commands

`/cd <path>` changes the current Workspace.

`/ws list` lists named Workspaces.

`/ws save <name>` stores the current Workspace under a name.

`/ws use <name>` switches to a named Workspace.

`/ws remove <name>` deletes a named Workspace.

`/cd <path>` and `/ws use <name>` interrupt the active Run and clear the current Agent Session.

Workspace paths must resolve to existing directories. The bridge rejects filesystem root, home root, system directories, and temporary directory roots. Workspace input must be an absolute path or use `~/...`.

## Attachments

The Personal Bridge baseline supports image and file Attachments.

Attachments are downloaded to a local cache and passed to the Agent Turn.

Attachments are not deleted immediately when a Run finishes. Cache cleanup is handled by a later retention policy.

Audio, video, and stickers are deferred capabilities.

## Run View

The Run View is a single streaming card.

Core produces provider-neutral Run View state. The Feishu Adapter renders that state as a card.

The Run View model contains:

- text blocks
- thinking blocks
- tool blocks
- Pending Request state
- terminal state

## Idle Timeout

Idle Timeout is supported but disabled by default.

The bridge supports a global value and a Private Chat Scope override through:

```text
/timeout [N|off|default]
```

`N` is a timeout duration in minutes.

## Pending Requests

Pending Requests cover approvals and user input.

When a Pending Request is open, the next owner message answers it instead of starting a new Run.

Run View actions may also answer or deny approval Pending Requests.

## Access Mode

The Personal Bridge uses one global Access Mode:

- `full`
- `workspace`
- `read-only`

Access Mode maps to concrete Agent Adapter permissions. It is not a user-level access policy.

## Configuration

The Personal Bridge uses a single local configuration profile.

Environment variables and a local config file are sufficient.

Profile creation, switching, exporting, archiving, and purging are outside the current baseline.

## Logs

The bridge writes structured local JSONL logs.

Required log streams:

- Run events
- Run errors
- startup diagnostics

Telemetry plugins are outside the current baseline.

## App Lifecycle

The app supports foreground startup and diagnostics.

Accepted CLI surface:

- `start`
- `doctor`

Daemon services, process registry commands, `/ps`, and `/exit` are outside the current baseline.
