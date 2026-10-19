# GitHub publication and repository setup

## Local setup completed

- Independent repository with `main` as the initial branch.
- Repository-local Git settings: LF files, safe line-ending checks, and fast-forward-only pulls.
- Existing author identity is inherited from the developer's Git configuration.
- Short-lived branch workflow documented in [CONTRIBUTING.md](../CONTRIBUTING.md).
- Documentation CI and a pull request template are included.
- GitHub Actions dependencies are pinned to full commit hashes; Dependabot proposes updates.

## Publication prerequisites

These are pending actions, not claims that GitHub settings are already configured.

- Confirm the GitHub owner/organization and repository slug; suggested slug: `simax-database-backup`.
- Select an open-source license, add `LICENSE`, and confirm attribution requirements with the project owner.
- Establish a private vulnerability-reporting channel and add `SECURITY.md` with supported versions and reporting instructions.
- Create the GitHub repository, set `origin`, push `main`, and push `docs/initial-prd` for its first PR.
- Set the default branch to `main` and enable GitHub Actions.
- Require a pull request, at least one approving review, resolved conversations, and both `Documentation checks` and `Application checks` statuses for merges to `main`.
- Block force pushes and branch deletion on `main`; restrict administrative bypass according to the maintainer policy.
- Enable squash merging and automatic deletion of merged branches.
- Enable available dependency and secret scanning; review availability for the chosen account.
- Run the workflow on GitHub and confirm its status before merging the PRD.

No remote, hosted repository, branch protection, or GitHub Actions run is established by local Git initialization.

## CI evolution

Current CI validates documentation, compiles Python, checks JavaScript syntax, runs API/service tests with synthetic adapter output, and builds a wheel. It requires no database credentials. Add live round-trip tests and publish the tested engine/version/platform matrix before claiming compatibility. Oracle and SQL Server test infrastructure and licensing constraints must be resolved before claiming those integrations are supported.

Use disposable databases and synthetic data. Fork pull requests must not receive production credentials. Release publishing and package signing belong in a separate reviewed workflow once distribution decisions are approved.
