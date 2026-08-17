# Domain docs

SC REVIT uses a single-context domain documentation layout.

## Before exploring

Read these files when they exist:

- `CONTEXT.md` at the project root.
- Relevant ADRs under `docs/adr/`.

If they do not exist, proceed silently. Domain-modeling work may create them
later when project terminology or architectural decisions are resolved.

## Layout

```text
/
├── CONTEXT.md
├── docs/
│   ├── agents/
│   │   ├── issue-tracker.md
│   │   └── domain.md
│   ├── adr/
│   └── decisions/
├── revit_addin/
├── revit_bridge/
└── sc_revit/
```

Existing records under `docs/decisions/` remain valid and are not
automatically moved into `docs/adr/`.

## Vocabulary

When naming domain concepts in issues, tests or architecture proposals, use
the terminology defined in `CONTEXT.md`. Do not silently introduce competing
synonyms.

## ADR conflicts

If proposed work conflicts with an existing ADR, identify that conflict
explicitly instead of silently replacing the decision.
