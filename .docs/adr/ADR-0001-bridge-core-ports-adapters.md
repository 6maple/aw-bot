# ADR-0001: Use Bridge Core with Ports and Adapters

## Status
Accepted

## Context

`c_auto_bridge` currently mixes Bridge behavior with Feishu, Codex, OpenCode, storage, and runtime assembly details. This keeps short-term code direct, but it lets Adapter vocabulary leak into shared records and orchestration. The clearest example is OpenCode behavior using fields named with Codex terms.

The project is choosing architecture cleanliness over compatibility for the next refactor.

## Decision

The highest-level architecture is Bridge Core with Ports and Adapters.

Bridge Core owns the stable domain behavior: turning Chat input into Agent Run progress, tracking Pending Requests, and producing Run View state.

Bridge Core uses Ports for outside behavior. Agent systems, Chat systems, persistence, and delivery mechanisms are Adapters. Runtime assembly is a composition root and does not own domain behavior.

Core vocabulary must stay provider-neutral. Names such as Agent Session and Agent Turn replace provider-specific names in shared Core records.

## Consequences

This makes Core behavior easier to reason about, test, and maintain independently from Feishu, Codex, and OpenCode details.

The refactor may rename fields, move modules, and break compatibility with existing persisted data or call sites.

Adapters will need explicit translation boundaries, so some code will move out of orchestration modules and into provider-specific Modules.
