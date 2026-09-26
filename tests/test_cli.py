import argparse

import pytest

from venv_cmds import cli


def test_build_parser_registers_both_commands():
    parser = cli.build_parser(cli._CONFIG, cli.COMMANDS)
    subparsers_action = next(
        a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
    )
    assert set(subparsers_action.choices) == {"list", "check_updates"}


def test_version_flag_prints_version_and_exits(capsys):
    parser = cli.build_parser(cli._CONFIG, cli.COMMANDS)

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--version"])

    assert exc_info.value.code == 0
    out, _ = capsys.readouterr()
    assert cli._CONFIG.version in out


def test_check_updates_args_parse_short_flags():
    parser = cli.build_parser(cli._CONFIG, cli.COMMANDS)

    args = parser.parse_args(["check_updates", "-u", "-t", "5", "-n"])

    assert args.updates_only is True
    assert args.timeout == 5
    assert args.no_progress is True
    assert args.func is cli.cmd_check_updates


def test_list_details_flag_parses():
    parser = cli.build_parser(cli._CONFIG, cli.COMMANDS)

    args = parser.parse_args(["list", "--details"])

    assert args.details is True
    assert args.func is cli.cmd_list


def test_main_with_no_subcommand_runs_list_with_defaults(monkeypatch):
    seen = {}

    def fake_cmd_list(args):
        seen["details"] = args.details

    monkeypatch.setitem(cli.COMMANDS["list"], "handler", fake_cmd_list)
    monkeypatch.setattr(cli.argcomplete, "autocomplete", lambda parser: None)
    monkeypatch.setattr("sys.argv", ["venv-cmds"])

    cli.main()

    assert seen == {"details": False}


def test_main_dispatches_to_explicit_subcommand(monkeypatch):
    seen = {}

    def fake_cmd_list(args):
        seen["called"] = True
        seen["details"] = args.details

    monkeypatch.setitem(cli.COMMANDS["list"], "handler", fake_cmd_list)
    monkeypatch.setattr(cli.argcomplete, "autocomplete", lambda parser: None)
    monkeypatch.setattr("sys.argv", ["venv-cmds", "list", "--details"])

    cli.main()

    assert seen == {"called": True, "details": True}
