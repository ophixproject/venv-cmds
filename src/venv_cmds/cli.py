import argparse
import re
import subprocess
import sys
import threading
import types
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

if sys.version_info >= (3, 8):
    from importlib.metadata import distributions, entry_points
else:
    from importlib_metadata import distributions, entry_points

from packaging.version import InvalidVersion, Version

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


_STATUS_OK          = "ok"
_STATUS_UPDATE      = "update"
_STATUS_UNAVAILABLE = "unavailable"
_STATUS_UNKNOWN     = "unknown"


def _get_latest_version(pip_name, timeout):
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "index", "versions", pip_name],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        match = re.search(r"Available versions:\s*(.+)", result.stdout)
        if match:
            versions = [v.strip() for v in match.group(1).split(",") if v.strip()]
            return versions[0] if versions else None
    except Exception:
        pass
    return None


def _compare(installed, latest):
    try:
        return _STATUS_UPDATE if Version(latest) > Version(installed) else _STATUS_OK
    except InvalidVersion:
        return _STATUS_UNKNOWN if installed != latest else _STATUS_OK


def _get_install_date(dist):
    try:
        path = getattr(dist, "_path", None)
        if path:
            return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")
    except Exception:
        pass
    return "—"


def _fetch_serial(packages, timeout, no_progress):
    total = len(packages)
    results = []
    prev_len = 0
    for i, (name, installed, install_date) in enumerate(packages, 1):
        if not no_progress:
            msg = "  Checking {} ({}/{})...".format(name, i, total)
            print(msg.ljust(prev_len), end="\r", file=sys.stderr, flush=True)
            prev_len = len(msg)
        latest = _get_latest_version(name, timeout)
        status = _STATUS_UNAVAILABLE if latest is None else _compare(installed, latest)
        results.append((name, installed, install_date, latest or "—", status))
    if not no_progress:
        print(" " * prev_len, end="\r", file=sys.stderr)
    return results


def _fetch_parallel(packages, timeout, no_progress, workers):
    total = len(packages)
    effective_workers = min(total, workers)
    if not no_progress:
        msg = "  Checking {} packages using {} workers...".format(total, effective_workers)
        print(msg, end="\r", file=sys.stderr, flush=True)
        prev_len = [len(msg)]
    else:
        prev_len = [0]
    lock = threading.Lock()
    counter = [0]
    result_map = {}

    def _fetch_one(name, installed, install_date):
        latest = _get_latest_version(name, timeout)
        status = _STATUS_UNAVAILABLE if latest is None else _compare(installed, latest)
        with lock:
            counter[0] += 1
            if not no_progress:
                msg = "  Checked {}/{}...".format(counter[0], total)
                print(msg.ljust(prev_len[0]), end="\r", file=sys.stderr, flush=True)
                prev_len[0] = len(msg)
        return name.lower(), (name, installed, install_date, latest or "—", status)

    with ThreadPoolExecutor(max_workers=effective_workers) as executor:
        futures = [executor.submit(_fetch_one, n, v, d) for n, v, d in packages]
        for future in as_completed(futures):
            key, value = future.result()
            result_map[key] = value

    if not no_progress:
        print(" " * prev_len[0], end="\r", file=sys.stderr)

    return [result_map[k] for k in sorted(result_map.keys())]


def cmd_check_updates(args):
    timeout = args.timeout
    output_file = args.output_file
    include_install_date = args.include_install_date
    updates_only = args.updates_only
    no_progress = args.no_progress
    fast = args.fast

    # Collect all installed distributions, deduplicated by normalised name.
    seen = {}
    for dist in distributions():
        name = dist.metadata.get("Name")
        version = dist.metadata.get("Version") or "unknown"
        if name and name.lower() not in seen:
            install_date = _get_install_date(dist) if include_install_date else None
            seen[name.lower()] = (name, version, install_date)

    packages = sorted(seen.values(), key=lambda x: x[0].lower())

    if fast:
        results = _fetch_parallel(packages, timeout, no_progress, args.workers)
    else:
        results = _fetch_serial(packages, timeout, no_progress)

    # When writing requirements to stdout, redirect table output to stderr
    # so the two streams stay separate and piping works cleanly.
    out = sys.stderr if output_file == "-" else sys.stdout

    # --- Table ---------------------------------------------------------------
    _labels = {
        _STATUS_OK:          "OK",
        _STATUS_UPDATE:      "UPDATE AVAILABLE",
        _STATUS_UNAVAILABLE: "unavailable",
        _STATUS_UNKNOWN:     "unknown",
    }

    col_pkg   = "Package"
    col_inst  = "Installed"
    col_date  = "Installed on"
    col_lat   = "Latest"
    col_stat  = "Status"

    rows = [
        (name, inst, idate, lat, _labels.get(st, st), st)
        for name, inst, idate, lat, st in results
    ]

    w_pkg  = max(len(col_pkg),  max(len(r[0]) for r in rows))
    w_inst = max(len(col_inst), max(len(r[1]) for r in rows))
    w_lat  = max(len(col_lat),  max(len(r[3]) for r in rows))
    w_stat = max(len(col_stat), max(len(r[4]) for r in rows))

    if include_install_date:
        w_date = max(len(col_date), max(len(r[2] or "—") for r in rows))
        fmt     = "{{:<{}}}  {{:<{}}}  {{:<{}}}  {{:<{}}}  {{}}".format(w_pkg, w_inst, w_date, w_lat)
        divider = "  ".join(["-" * w_pkg, "-" * w_inst, "-" * w_date, "-" * w_lat, "-" * w_stat])
        header  = fmt.format(col_pkg, col_inst, col_date, col_lat, col_stat)
    else:
        fmt     = "{{:<{}}}  {{:<{}}}  {{:<{}}}  {{}}".format(w_pkg, w_inst, w_lat)
        divider = "  ".join(["-" * w_pkg, "-" * w_inst, "-" * w_lat, "-" * w_stat])
        header  = fmt.format(col_pkg, col_inst, col_lat, col_stat)

    updates = [r for r in rows if r[5] == _STATUS_UPDATE]
    display_rows = updates if updates_only else rows

    if display_rows:
        print(header, file=out)
        print(divider, file=out)
        for name, inst, idate, lat, label, raw_status in display_rows:
            if include_install_date:
                print(fmt.format(name, inst, idate or "—", lat, label), file=out)
            else:
                print(fmt.format(name, inst, lat, label), file=out)
        print(file=out)

    if not updates_only:
        if updates:
            print("{} update(s) available.".format(len(updates)), file=out)
        else:
            print("All packages are up to date.", file=out)
    elif updates:
        print("{} update(s) available.".format(len(updates)), file=out)

    unavailable = sum(1 for r in rows if r[5] == _STATUS_UNAVAILABLE)
    if unavailable:
        print("{} package(s) could not be checked (not found in configured index or index unreachable).".format(unavailable), file=out)

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
    version=__version__,
)

COMMANDS = {
    "list": {
        "help": "List console_scripts entry points in the active environment (default).",
        "arguments": [
            {"name": "--details", "action": "store_true", "help": "Show package name alongside each command."},
        ],
        "handler": cmd_list,
    },
    "check_updates": {
        "help": "Check all installed packages against the configured pip index for available updates.",
        "arguments": [
            {
                "name": "--timeout",
                "type": int,
                "default": 30,
                "metavar": "SECONDS",
                "help": "Per-package pip query timeout in seconds (default: 30).",
            },
            {
                "name": "--output-file",
                "metavar": "FILE",
                "default": None,
                "help": "Write packages with available updates to FILE in requirements.txt format.",
            },
            {
                "name": "--updates-only",
                "action": "store_true",
                "default": False,
                "help": "Only show packages with available updates. Produces no output when everything is current.",
            },
            {
                "name": "--include-install-date",
                "action": "store_true",
                "default": False,
                "help": "Add an 'Installed on' column showing when each package was installed (approximated from dist-info mtime).",
            },
            {
                "name": "--no-progress",
                "action": "store_true",
                "default": False,
                "help": "Suppress the per-package progress line written to stderr. Useful when running from cron.",
            },
            {
                "name": "--fast",
                "action": "store_true",
                "default": False,
                "help": "Check all packages in parallel using a thread pool. Significantly faster for large environments.",
            },
            {
                "name": "--workers",
                "type": int,
                "default": 16,
                "metavar": "N",
                "help": "Number of parallel workers when using --fast (default: 16).",
            },
        ],
        "handler": cmd_check_updates,
    },
}


# ---------------------------------------------------------------------------
# Parser builder and entry point
# ---------------------------------------------------------------------------

def build_parser(config, commands):
    parser = argparse.ArgumentParser(prog=config.prog, description=config.description)
    parser.add_argument("--version", action="version", version="{} {}".format(config.prog, config.version))

    subparsers = parser.add_subparsers(dest="command")

    for name, spec in commands.items():
        help_text = argparse.SUPPRESS if spec.get("hidden") else spec.get("help")
        sub = subparsers.add_parser(name, help=help_text)

        for arg in spec.get("arguments", []):
            arg = arg.copy()
            arg_name = arg.pop("name")
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
        args = parser.parse_args()

        if not hasattr(args, "func"):
            # No subcommand given — run the default.
            sub_spec = commands[default_cmd]
            for arg in sub_spec.get("arguments", []):
                attr = arg["name"].lstrip("-").replace("-", "_")
                if not hasattr(args, attr):
                    setattr(args, attr, arg.get("default", None))
            sub_spec["handler"](args)
        else:
            args.func(args)

    return main


main = make_main(_CONFIG, COMMANDS)
