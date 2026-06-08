# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Layout

This is a single-context repo. The domain documentation lives under `.docs/` instead of the repository root:

- Glossary: `.docs/CONTEXT.md`
- ADRs: `.docs/adr/`
- Architecture notes: `.docs/architecture/`
- PRDs: `.docs/prd/`

## Before exploring, read these

- Read `.docs/CONTEXT.md` before naming domain concepts in issues, plans, test names, or refactor proposals.
- Read relevant ADRs under `.docs/adr/` before changing architectural boundaries or adapter behavior.
- Read relevant notes under `.docs/architecture/` or `.docs/prd/` when the task touches accepted workflow or provider adapter behavior.

If a document does not exist, proceed silently. The producer skill (`grill-with-docs`) creates domain docs lazily when terms or decisions are resolved.

## Use the glossary's vocabulary

When output names a domain concept, use the term as defined in `.docs/CONTEXT.md`. Do not drift to synonyms the glossary explicitly avoids.

If the concept needed is not in the glossary yet, either reconsider whether the project already has a better term or note the gap for `grill-with-docs`.

## Flag ADR conflicts

If output contradicts an existing ADR, surface it explicitly rather than silently overriding it:

> Contradicts ADR-0001 (Use Bridge Core with Ports and Adapters), but worth reopening because...
