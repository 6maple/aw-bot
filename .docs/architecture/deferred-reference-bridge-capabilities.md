# Deferred Reference Bridge Capabilities

## Status

Archived for future extension.

## Purpose

This document records capabilities from `D:\Workspace\github\lark-coding-agent-bridge` that are intentionally outside the current `aw-bot` architecture baseline.

They are not rejected permanently. They are deferred so the current refactor can stay focused on a Personal Bridge for one owner.

## Deferred Capabilities

### Group Chat

Support for group chat message intake, group mention rules, and group-specific reply behavior.

### Topic Scope

Support for topic-group scopes where each topic thread owns an independent session, workspace, pending queue, and active Run.

These capabilities require reintroducing a multi-scope Chat model. The current baseline intentionally uses one Private Chat Scope.

### Access Policy

Support for invite/remove/admin commands, allowed users, allowed chats, group allowlists, and multi-user authorization checks.

### Multi-Profile Management

Support for multiple named profiles, active profile switching, profile export, profile removal, and separate profile-local state roots.

### Daemon and Service Management

Support for platform service registration and lifecycle commands such as start, stop, restart, status, and unregister.

### Process Registry

Support for local bridge process discovery and control commands such as `/ps` and `/exit`.

### Cloud Document Comments

Support for cloud document comment intake, comment-thread replies, and document-level session scope.

### Multi-User Lark CLI Identity

Support for switching between bot-only and user-default `lark-cli` identity policies across multiple users.

### Telemetry Plugin

Support for externally supplied telemetry adapters.

### Non-File Media Attachments

Support for audio, video, and stickers as first-class Agent inputs.

### Productized Profile Lifecycle

Support for creating, switching, exporting, archiving, and purging multiple profiles.

## Reconsideration Rule

A deferred capability can be reconsidered when it supports the Personal Bridge workflow or when the project explicitly expands beyond one-owner private use.

When reconsidered, define the Core term first, then add or extend Ports. Do not introduce external-system vocabulary into Core records.
