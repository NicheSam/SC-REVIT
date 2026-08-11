# ADR-001: Separate the development and release-record workspaces

## Status

Accepted

## Date

2026-08-10

## Context

SC REVIT previously had changes made in both `E:\Desktop\Codex\SC REVIT` and
`E:\Desktop\Codex\PushGithub\SC REVIT`. This allowed an older development tree
to overwrite a newer released Revit DLL and GUI while still appearing to be an
update.

## Decision

- `E:\Desktop\Codex\SC REVIT` is the only development workspace. All source
  changes, local builds, tests, sandbox checks, and deployments start here.
- `E:\Desktop\Codex\PushGithub\SC REVIT` is the Git release-record workspace.
  Do not develop directly in it. Copy only a reviewed and verified release
  candidate into it when preparing a commit, tag, installer, or GitHub release.
- A release-record snapshot may be used as the baseline for a new development
  version, but it must first be copied into a separate staging workspace. Never
  overwrite the development workspace directly from the record workspace.
- Revit DLL, GUI executable, manifest, and version metadata must be built and
  verified from the same development snapshot before deployment.

## Consequences

- Development work has one authoritative location.
- Git history remains a clean publication boundary instead of a live working
  directory.
- Integrations must preserve a recoverable backup until the new development
  workspace passes build and test verification.
- Existing `bin`, `dist`, installed DLLs, and timestamps are not accepted as
  version evidence; source baseline and hashes are recorded during deployment.

## Alternatives considered

### Develop directly in PushGithub

Rejected because the user requires PushGithub to remain a release and history
boundary, not an active development tree.

### Continue maintaining multiple development folders

Rejected because feature and deployment drift already caused a real regression.
