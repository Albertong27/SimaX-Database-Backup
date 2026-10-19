# SimaX Database Backup

A planned database backup and restore application by **Simply Smart X (SimaX)**.

Status: product definition. There is no runnable application yet.

The intended scope covers MySQL, PostgreSQL, Oracle Database, and Microsoft SQL Server; configurable backup triggers; selective database objects; local, remote, and cloud destinations; and restoration to a compatible server.

## Project documents

The detailed PRD will be developed on `docs/initial-prd` before review into `main`.

- [Contributing and branch workflow](CONTRIBUTING.md)
- [GitHub publication checklist](docs/github-setup.md)

## Local checks

Run with Python 3.10 or later and Git installed:

```sh
python scripts/check_docs.py
git diff --check
```

GitHub Actions runs the same documentation check on pushes and pull requests. Application build, database integration, and recovery tests will be added when implementation begins.

## License status

This project is intended for open-source publication. The license has not yet been selected; no open-source license grant is currently provided. Selecting a license and adding its full text are publication prerequisites.
