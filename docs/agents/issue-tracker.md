# Issue tracker: GitHub

Issues and specifications for SC REVIT live in GitHub Issues:

- Repository: `NicheSam/SC-REVIT`
- Development source: `E:\Desktop\Codex\SC REVIT`
- Git publication staging: `E:\Desktop\Codex\PushGithub\SC REVIT`

The development source is not itself a Git clone. Always pass
`--repo NicheSam/SC-REVIT` to `gh` commands instead of relying on
the current working directory.

## Conventions

- Create: `gh issue create --repo NicheSam/SC-REVIT --title "..." --body-file <utf8-file>`
- Read: `gh issue view <number> --repo NicheSam/SC-REVIT --comments`
- List: `gh issue list --repo NicheSam/SC-REVIT --state open`
- Comment: `gh issue comment <number> --repo NicheSam/SC-REVIT --body-file <utf8-file>`
- Edit labels: `gh issue edit <number> --repo NicheSam/SC-REVIT --add-label "..."`
- Close: `gh issue close <number> --repo NicheSam/SC-REVIT`

Do not edit product source inside `PushGithub\SC REVIT`. That directory is
only the Git publication and release staging copy.

## Pull requests as a triage surface

PRs as a request surface: no.

## Skill terminology

When a skill says "publish to the issue tracker", create a GitHub issue in
`NicheSam/SC-REVIT`.

When a skill says "fetch the relevant ticket", read the corresponding
GitHub issue and its comments.
