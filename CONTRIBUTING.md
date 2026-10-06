# Contributing to Claude in Codex

Small, focused contributions are welcome. For a major behavior change, open an issue first so we can agree on scope and compatibility.

## Development setup

You need Git and Python 3.10 or newer on macOS or Linux. The CLI has no runtime dependencies.

```bash
git clone https://github.com/prashan-s/claude-in-codex.git
cd claude-in-codex
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
cic --help
```

Claude Code authentication is needed for real agent runs. It is not needed for the automated tests. You do not need to run `install.sh` to develop or test the Python CLI.

## Before opening a pull request

```bash
python -m unittest discover -s tests -v
python scripts/check_install.py
bash -n install.sh uninstall.sh
git diff --check
```

The suite uses `tests/fake_claude.py` to exercise the real CLI and detached workers without sending API requests. Keep new tests isolated from personal configuration, credentials, and installed agents. Do not add tests that need paid API calls or a logged-in account.

For packaging changes, also run:

```bash
python -m pip install build twine
python -m build
python -m twine check dist/*
```

If changing GitHub workflows, validate them with `actionlint` when available. CI runs tests and installer checks on Linux and macOS with Python 3.10–3.14, and builds and checks the Python distributions.

## Scope and review

- Create a branch and open a pull request against `main`.
- Keep each change focused; preserve existing contracts and architecture.
- Explain the problem, resulting behavior, and checks you ran.
- Add meaningful regression coverage for behavior changes, including relevant failure paths.
- Update affected CLI help, README sections, and skills together.
- Keep secrets, private paths, agent transcripts, and generated state out of commits and issue reports.
- Be explicit about checks you could not run. A passing fake-agent test does not establish compatibility with a real agent CLI.

Maintainers review changes before merging. There is no guaranteed review or response time. Contributions are licensed under the repository's [MIT license](LICENSE).

## Versions and releases

Maintainers use semantic versions without a `v` prefix: `1.0.0`, `1.1.0`, `1.1.1`, and so on. MAJOR changes break compatibility, MINOR changes add compatible features, and PATCH changes fix bugs compatibly. Contributors normally leave the version unchanged unless the pull request prepares a release.

To release:

1. Update the version in `pyproject.toml`, `src/cic/__init__.py`, and `.codex-plugin/plugin.json` together.
2. Commit and push the changes to `main`; confirm CI passes.
3. Create an annotated tag matching those versions and push it:

   ```bash
   git tag -a 1.0.0 -m "Release 1.0.0"
   git push origin 1.0.0
   ```

   Substitute the new version when preparing subsequent releases.

4. Confirm the Release workflow passes and the GitHub release contains the wheel and source distribution.

The workflow reruns CI and rejects malformed or mismatched versions before publishing. Source archives also contain the installer and skills. Releases are published to GitHub, not PyPI. Do not move or overwrite a published release tag; correct a release with a new PATCH version.

## Community and security

Follow the [Code of Conduct](CODE_OF_CONDUCT.md). For vulnerabilities, use the private process in [SECURITY.md](SECURITY.md), rather than opening a public issue.
