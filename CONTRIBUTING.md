# Contributing

SimaX Database Backup is maintained under Simply Smart X (SimaX). The project is currently defining requirements; implementation choices remain open.

## Git workflow

- `main` is the reviewed integration branch.
- Create short-lived branches from current `main`: `docs/<topic>`, `feat/<topic>`, `fix/<topic>`, or `chore/<topic>`.
- The initial PRD is prepared on `docs/initial-prd`.
- Use focused commits with prefixes such as `docs:`, `feat:`, `fix:`, and `chore:`.
- Submit a pull request explaining the problem, resulting behavior, and relevant validation.
- Keep changes reviewable; squash merge approved PRs and delete merged branches.
- Do not force-push shared branches or commit directly to `main` after initial bootstrap.
- Keep credentials, production dumps, personal data, and local runtime state out of Git.

Example once a GitHub remote is configured:

```sh
git switch main
git pull --ff-only
git switch -c docs/refine-recovery-requirements
python scripts/check_docs.py
git diff --check
git add docs/
git commit -m "docs: refine recovery requirements"
git push -u origin docs/refine-recovery-requirements
```

## Documentation checks

Run `python scripts/check_docs.py` with Python 3.10+ from the repository root. The dependency-free check validates tracked Markdown files for UTF-8, LF line endings, final newlines, trailing whitespace, conflict markers, and local inline-link file targets. It does not validate URL availability, heading anchors, or every Markdown dialect. Use relative file links without spaces or optional titles in repository documentation.

For new files, stage them before running checks so Git includes them in the tracked file list. Run `git diff --check` before committing.

## Requirements and design

Keep user problems separate from proposed implementations. Label assumptions, unvalidated targets, and unresolved decisions. Cite official documentation for engine-specific limitations. A capability is supported only after its backup and restore paths have passed a published test matrix.

## Public contributions

The project owner must select an open-source license and publish contribution and security-reporting policies before inviting public contributions. Do not infer a license from the project name or intended publication.
