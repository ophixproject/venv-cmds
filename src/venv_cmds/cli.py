# PYTHON_ARGCOMPLETE_OK
import argparse
import json
import shutil
import subprocess
import sys
import types
from datetime import datetime
from pathlib import Path

import argcomplete

if sys.version_info >= (3, 8):
    from importlib.metadata import distributions, entry_points
else:
    from importlib_metadata import distributions, entry_points

from venv_cmds._version import __version__

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _in_venv():
    return sys.prefix != getattr(sys, "base_prefix", sys.prefix)

def _venv_name():
    return Path(sys.prefix).name

# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def cmd_list(args):
    if _in_venv():
        print("Info: detected virtual environment '{}'".format(_venv_name()))
    else:
        print("Warning: no virtual environment detected; listing system-wide commands.", file=sys.stderr)

    if sys.version_info >= (3, 9):
        eps = entry_points(group="console_scripts")
    else:
        eps = entry_points().get("console_scripts", [])

    for ep in sorted(eps, key=lambda e: e.name):
        if getattr(args, "details", False):
            dist = getattr(ep, "dist", None)
            pkg_name = dist.metadata.get("Name", "unknown") if dist else "unknown"
            print("{} (package: {})".format(ep.name, pkg_name))
        else:
            print(ep.name)


_STATUS_OK     = "ok"
_STATUS_UPDATE = "update"


def _pip_list_json(extra_args, timeout):
    # Falls back to `uv pip list` if pip isn't importable in this environment
    # (e.g. a venv created with `uv venv` without --seed). --python targets
    # this exact interpreter rather than relying on VIRTUAL_ENV being set.
    result = subprocess.run(
        [sys.executable, "-m", "pip", "list", "--format=json"] + extra_args,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        uv_path = shutil.which("uv")
        if uv_path:
            result = subprocess.run(
                [uv_path, "pip", "list", "--format=json", "--python", sys.executable] + extra_args,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
    if result.returncode != 0:
        print("Error: pip list failed:\n{}".format(result.stderr.strip()), file=sys.stderr)
        sys.exit(1)
    return json.loads(result.stdout)


def _get_install_date(dist):
    try:
        path = getattr(dist, "_path", None)
        if path:
            return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")
    except Exception:
        pass
    return "—"


def cmd_check_updates(args):
    timeout = args.timeout
    output_file = args.output_file
    include_install_date = args.include_install_date
    updates_only = args.updates_only
    no_progress = args.no_progress

    if not no_progress:
        print("  Querying index...", end="\r", file=sys.stderr, flush=True)

    outdated = _pip_list_json(["--outdated"], timeout)

    if updates_only:
        # Single pip call sufficient — no need to fetch the full package list.
        all_pkgs = outdated
    else:
        all_pkgs = _pip_list_json([], timeout)

    if not no_progress:
        print("                   ", end="\r", file=sys.stderr)

    outdated_map = {p["name"].lower(): p["latest_version"] for p in outdated}

    # Build install-date lookup from importlib.metadata if needed.
    if include_install_date:
        dist_map = {}
        for dist in distributions():
            name = dist.metadata.get("Name")
            if name:
                dist_map[name.lower()] = dist

    results = []
    for pkg in sorted(all_pkgs, key=lambda p: p["name"].lower()):
        name      = pkg["name"]
        installed = pkg["version"]
        key       = name.lower()
        latest    = outdated_map.get(key)
        status    = _STATUS_UPDATE if latest else _STATUS_OK
        if not latest:
            latest = installed
        install_date = _get_install_date(dist_map[key]) if include_install_date and key in dist_map else None
        results.append((name, installed, install_date, latest, status))

    # When writing requirements to stdout, redirect table output to stderr
    # so the two streams stay separate and piping works cleanly.
    out = sys.stderr if output_file == "-" else sys.stdout

    # --- Table ---------------------------------------------------------------
    col_pkg  = "Package"
    col_inst = "Installed"
    col_date = "Installed on"
    col_lat  = "Latest"
    col_stat = "Status"

    label = {_STATUS_OK: "OK", _STATUS_UPDATE: "UPDATE AVAILABLE"}

    rows = [
        (name, inst, idate, lat, label[st], st)
        for name, inst, idate, lat, st in results
    ]

    updates      = [r for r in rows if r[5] == _STATUS_UPDATE]
    display_rows = updates if updates_only else rows

    if display_rows:
        w_pkg  = max(len(col_pkg),  max(len(r[0]) for r in display_rows))
        w_inst = max(len(col_inst), max(len(r[1]) for r in display_rows))
        w_lat  = max(len(col_lat),  max(len(r[3]) for r in display_rows))
        w_stat = max(len(col_stat), max(len(r[4]) for r in display_rows))

        if include_install_date:
            w_date  = max(len(col_date), max(len(r[2] or "—") for r in display_rows))
            fmt     = "{{:<{}}}  {{:<{}}}  {{:<{}}}  {{:<{}}}  {{}}".format(w_pkg, w_inst, w_date, w_lat)
            divider = "  ".join(["-" * w_pkg, "-" * w_inst, "-" * w_date, "-" * w_lat, "-" * w_stat])
            header  = fmt.format(col_pkg, col_inst, col_date, col_lat, col_stat)
        else:
            fmt     = "{{:<{}}}  {{:<{}}}  {{:<{}}}  {{}}".format(w_pkg, w_inst, w_lat)
            divider = "  ".join(["-" * w_pkg, "-" * w_inst, "-" * w_lat, "-" * w_stat])
            header  = fmt.format(col_pkg, col_inst, col_lat, col_stat)

        print(header, file=out)
        print(divider, file=out)
        for name, inst, idate, lat, lbl, _ in display_rows:
            if include_install_date:
                print(fmt.format(name, inst, idate or "—", lat, lbl), file=out)
            else:
                print(fmt.format(name, inst, lat, lbl), file=out)
        print(file=out)

    if not updates_only:
        if updates:
            print("{} update(s) available.".format(len(updates)), file=out)
        else:
            print("All packages are up to date.", file=out)
    elif updates:
        print("{} update(s) available.".format(len(updates)), file=out)

    if output_file:
        if not updates:
            print("No updates available — {} not written.".format(output_file), file=out)
        elif output_file == "-":
            sys.stdout.write("\n".join("{}=={}".format(r[0], r[3]) for r in updates) + "\n")
        else:
            path = Path(output_file)
            path.write_text("\n".join("{}=={}".format(r[0], r[3]) for r in updates) + "\n", encoding="utf-8")
            print("Update list written to {} ({} package(s)).".format(path, len(updates)), file=out)


# ---------------------------------------------------------------------------
# Declarative CLI structure
# ---------------------------------------------------------------------------

_CONFIG = types.SimpleNamespace(
    prog="venv-cmds",
    description="Inspect the active Python environment.",
    epilog="Tab completion: run activate-global-python-argcomplete once per user account to enable.",
    version=__version__,
)

COMMANDS = {
    "list": {
        "help": "List console_scripts entry points in the active environment (default).",
        "arguments": [
            {"name": ["-d", "--details"], "action": "store_true", "help": "Show package name alongside each command."},
        ],
        "handler": cmd_list,
    },
    "check_updates": {
        "help": "Check all installed packages against the configured pip index for available updates.",
        "arguments": [
            {
                "name": ["-t", "--timeout"],
                "type": int,
                "default": 30,
                "metavar": "SECONDS",
                "help": "Per-package pip query timeout in seconds (default: 30).",
            },
            {
                "name": ["-o", "--output-file"],
                "metavar": "FILE",
                "default": None,
                "help": "Write packages with available updates to FILE in requirements.txt format.",
            },
            {
                "name": ["-u", "--updates-only"],
                "action": "store_true",
                "default": False,
                "help": "Only show packages with available updates. Produces no output when everything is current.",
            },
            {
                "name": ["-i", "--include-install-date"],
                "action": "store_true",
                "default": False,
                "help": "Add an 'Installed on' column showing when each package was installed (approximated from dist-info mtime).",
            },
            {
                "name": ["-n", "--no-progress"],
                "action": "store_true",
                "default": False,
                "help": "Suppress the status message written to stderr while querying the index. Useful when running from cron.",
            },
        ],
        "handler": cmd_check_updates,
    },
}


# ---------------------------------------------------------------------------
# Parser builder and entry point
# ---------------------------------------------------------------------------

def build_parser(config, commands):
    parser = argparse.ArgumentParser(prog=config.prog, description=config.description, epilog=getattr(config, "epilog", None))
    parser.add_argument("--version", action="version", version="{} {}".format(config.prog, config.version))

    subparsers = parser.add_subparsers(dest="command")

    for name, spec in commands.items():
        help_text = argparse.SUPPRESS if spec.get("hidden") else spec.get("help")
        sub = subparsers.add_parser(name, help=help_text)

        for arg in spec.get("arguments", []):
            arg = arg.copy()
            arg_name = arg.pop("name")
            if isinstance(arg_name, list):
                sub.add_argument(*arg_name, **arg)
            else:
                sub.add_argument(arg_name, **arg)

        for group_spec in spec.get("mutually_exclusive_groups", []):
            group = sub.add_mutually_exclusive_group(required=group_spec.get("required", False))
            for arg in group_spec["arguments"]:
                arg = arg.copy()
                arg_name = arg.pop("name")
                group.add_argument(arg_name, **arg)

        sub.set_defaults(func=spec["handler"])

    return parser


def make_main(config, commands):
    default_cmd = "list"

    def main():
        parser = build_parser(config, commands)
        argcomplete.autocomplete(parser)
        args = parser.parse_args()

        if not hasattr(args, "func"):
            # No subcommand given — reparse as the default command so argparse
            # fills in the same defaults it would for an explicit invocation
            # (e.g. store_true flags default to False, not None).
            args = parser.parse_args([default_cmd])

        args.func(args)

    return main


main = make_main(_CONFIG, COMMANDS)
