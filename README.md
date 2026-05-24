# venv-cmds

Small discovery and maintenance utilities for Python virtual environments.

## Why this exists

When you activate a virtual environment it is not always obvious which
command-line tools are available or whether they are up to date.
`venv-cmds` provides two commands: `list` to discover what is installed,
and `check_updates` to check for newer versions on the configured pip index.

## Commands

Running `venv-cmds` with no subcommand is equivalent to `venv-cmds list`.

### `list`

Show all `console_scripts` entry points in the active environment.

```bash
venv-cmds list
venv-cmds list --details    # include package name alongside each command
```

### `check_updates`

Check all installed packages against the configured pip index and report
which have updates available. Respects all pip index sources configured for
the environment — public PyPI, private indexes, and local mirrors all work
without any extra configuration.

```bash
venv-cmds check_updates
venv-cmds check_updates --updates-only            # only show packages with updates
venv-cmds check_updates --no-progress             # suppress per-package progress (cron-safe)
venv-cmds check_updates --include-install-date    # add an 'Installed on' column
venv-cmds check_updates --timeout 60              # per-package query timeout in seconds (default: 30)
venv-cmds check_updates --output-file updates.txt # write pinned requirements file for updates
venv-cmds check_updates --output-file -           # write pinned requirements to stdout
```

When `--output-file` is used the output file contains `package==version` lines
for every package with an available update. Passing this file to
`pip install -r updates.txt` will upgrade exactly the packages that were
flagged, with no other changes.

## Installation

```bash
pip install venv-cmds
```

Requires Python 3.7 or later. Works with both `venv` and `virtualenv`.
