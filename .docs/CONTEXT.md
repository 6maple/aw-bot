# CONTEXT

Project glossary. Add stable domain terms only.

## Bridge Core

The Module that turns Chat input into Agent Run progress and produces Run View state.

## Chat

The conversation scope where a User sends input and receives Run View updates.

## Private Chat Scope

The single owner Chat scope used by the Personal Bridge.

## Workspace

The local directory used by Agent Turns.

## Queued Message

A Chat message, including any supported Attachments, held until the active Run finishes.

## Message Merge Window

The short interval where consecutive Queued Messages are combined into one Agent Turn prompt.

## Attachment

A Chat-provided local input, such as an image or file, passed to an Agent Turn.

## Agent

An external coding system that maintains Agent Sessions and executes Agent Turns.
_Avoid_: Provider, model, bot

## Idle Timeout

A watchdog that interrupts a Run after the Agent produces no output for the configured duration.

## Access Mode

The owner-selected execution permission level for Agent Turns.

## User

The human actor who owns Agent Sessions and answers Pending Requests.

## Agent Session

The durable conversation identity maintained by an Agent.

## Agent Turn

One Agent execution started from User input inside an Agent Session.

## Run

The Bridge Core record of one Agent Turn progressing through states.

## Pending Request

A Run pause that requires User input or approval before the Agent Turn can continue.

## Run View

The user-facing representation of Run state.

## Port

An Interface owned by the Bridge Core for behavior supplied from outside the Core.

## Adapter

A concrete implementation of a Port for an external system.

## Personal Bridge

A Bridge used by one owner in a private Chat workflow.
