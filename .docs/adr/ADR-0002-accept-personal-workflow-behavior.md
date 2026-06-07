# ADR-0002: Accept Personal Workflow Behavior

## Status
Accepted

## Context

The Personal Bridge architecture has accepted a one-owner private workflow and functional alignment with the reference bridge's personal semantics.

The remaining design choices affect multiple Core Modules and Ports, including queueing, session continuation, workspace handling, attachments, run view rendering, timeout handling, permissions, configuration, logs, and app lifecycle.

## Decision

Accept `personal-workflow-behavior.md` as the behavior baseline for the refactor.

Key decisions:

- active Run messages are queued and merged
- Message Merge Window is fixed at 1.5 seconds
- `/new` and `/reset` interrupt the active Run and clear the current Agent Session while preserving Workspace
- `/resume` only restores same Agent, same Workspace, compatible Access Mode sessions
- `/cd` and `/ws use` interrupt the active Run and clear the current Agent Session
- Workspace paths must be existing safe directories
- image and file Attachments are supported; audio, video, and stickers are deferred
- Run View is a single streaming card
- Idle Timeout is supported and disabled by default
- Access Mode is global and owner-selected, not a user access policy
- configuration is single-profile local config
- logs are structured local JSONL
- app lifecycle is foreground `start` and `doctor`

## Consequences

The refactor has a concrete behavior target without importing reference bridge complexity that exists for groups, multiple users, daemon operation, or productized profile management.

Core Modules can be designed around personal workflow locality and small Ports.

Future expansion must either extend this behavior baseline or move a deferred capability out of the archive.
