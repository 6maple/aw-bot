# ADR-0003: Use Codex CLI App Server over stdio

## Status
Accepted

## Context

`aw-bot` needs Codex support that preserves Agent Sessions, streaming Run progress, Pending Requests, approval handling, and Attachment input. The obvious alternatives are a one-shot `codex exec` process, a WebSocket App Server endpoint, or a managed local Codex CLI App Server over stdio.

## Decision

Use the local Codex CLI App Server as the Codex Adapter boundary, defaulting to `codex app-server --listen stdio://`. `CODEX_APP_SERVER_URL` remains an explicit advanced override for WebSocket use, but the default is stdio.

Codex configuration values should mostly come from Codex itself. `CODEX_HOME`, `CODEX_WORKSPACE`, `CODEX_MODEL`, and `CODEX_APPROVAL_POLICY` are optional overrides; when omitted, Codex home uses the CLI default, Workspace starts from the bridge process cwd, and model/approval use Codex configuration. `CODEX_SANDBOX` defaults to `workspace-write`; the current Codex Adapter accepts only that mode because the current Bridge Access Mode is `workspace`.

Codex Attachment input maps image Attachments to `localImage` UserInput and file Attachments to `mention` UserInput. Unsupported media kinds are skipped. Codex permission approval requests are handled as normal approval Pending Requests.

## Consequences

This keeps Codex behavior aligned with Bridge Core concepts instead of flattening turns into one-shot CLI calls. Startup is easier because users can rely on their existing Codex CLI configuration, while WebSocket remains available for manual App Server setups.
