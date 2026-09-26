import json
import subprocess
import types

import pytest

from venv_cmds import cli


def _completed(returncode=0, stdout="", stderr=""):
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


def _args(**overrides):
    defaults = dict(
        timeout=30,
        output_file=None,
        updates_only=False,
        include_install_date=False,
        no_progress=True,
    )
    defaults.update(overrides)
    return types.SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# _pip_list_json
# ---------------------------------------------------------------------------

def test_pip_list_json_uses_pip_when_it_succeeds(monkeypatch):
    payload = [{"name": "foo", "version": "1.0"}]
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        return _completed(0, stdout=json.dumps(payload))

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = cli._pip_list_json([], timeout=5)

    assert result == payload
    assert len(calls) == 1
    assert "pip" in calls[0]


def test_pip_list_json_falls_back_to_uv_when_pip_fails(monkeypatch):
    payload = [{"name": "bar", "version": "2.0"}]
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if "uv" in cmd[0]:
            return _completed(0, stdout=json.dumps(payload))
        return _completed(1, stderr="pip not importable")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/uv")

    result = cli._pip_list_json([], timeout=5)

    assert result == payload
    assert len(calls) == 2
    assert "--python" in calls[1]


def test_pip_list_json_exits_when_both_pip_and_uv_fail(monkeypatch, capsys):
    def fake_run(cmd, **kwargs):
        return _completed(1, stderr="boom")

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)

    with pytest.raises(SystemExit) as exc_info:
        cli._pip_list_json([], timeout=5)

    assert exc_info.value.code == 1
    _, err = capsys.readouterr()
    assert "boom" in err


# ---------------------------------------------------------------------------
# _get_install_date
# ---------------------------------------------------------------------------

def test_get_install_date_from_path_mtime(tmp_path):
    marker = tmp_path / "pkg.dist-info"
    marker.write_text("x")

    dist = types.SimpleNamespace(_path=marker)

    result = cli._get_install_date(dist)

    assert len(result) == 10
    assert result.count("-") == 2


def test_get_install_date_returns_placeholder_without_path():
    dist = types.SimpleNamespace()

    assert cli._get_install_date(dist) == "—"


# ---------------------------------------------------------------------------
# cmd_check_updates
# ---------------------------------------------------------------------------

def test_check_updates_all_current(monkeypatch, capsys):
    all_pkgs = [{"name": "alpha", "version": "1.0"}]

    def fake_pip_list_json(extra_args, timeout):
        return [] if extra_args == ["--outdated"] else all_pkgs

    monkeypatch.setattr(cli, "_pip_list_json", fake_pip_list_json)

    cli.cmd_check_updates(_args())

    out, _ = capsys.readouterr()
    assert "alpha" in out
    assert "OK" in out
    assert "All packages are up to date." in out


def test_check_updates_reports_available_update(monkeypatch, capsys):
    def fake_pip_list_json(extra_args, timeout):
        if extra_args == ["--outdated"]:
            return [{"name": "alpha", "version": "1.0", "latest_version": "2.0"}]
        return [{"name": "alpha", "version": "1.0"}, {"name": "beta", "version": "3.0"}]

    monkeypatch.setattr(cli, "_pip_list_json", fake_pip_list_json)

    cli.cmd_check_updates(_args())

    out, _ = capsys.readouterr()
    assert "alpha" in out and "UPDATE AVAILABLE" in out
    assert "beta" in out and "OK" in out
    assert "1 update(s) available." in out


def test_check_updates_only_flag_hides_current_packages(monkeypatch, capsys):
    def fake_pip_list_json(extra_args, timeout):
        # updates_only mode should never request the full package list
        assert extra_args == ["--outdated"]
        return [{"name": "alpha", "version": "1.0", "latest_version": "2.0"}]

    monkeypatch.setattr(cli, "_pip_list_json", fake_pip_list_json)

    cli.cmd_check_updates(_args(updates_only=True))

    out, _ = capsys.readouterr()
    assert "alpha" in out
    assert "beta" not in out


def test_check_updates_writes_output_file(monkeypatch, tmp_path):
    def fake_pip_list_json(extra_args, timeout):
        if extra_args == ["--outdated"]:
            return [{"name": "alpha", "version": "1.0", "latest_version": "2.0"}]
        return [{"name": "alpha", "version": "1.0"}]

    monkeypatch.setattr(cli, "_pip_list_json", fake_pip_list_json)

    out_file = tmp_path / "updates.txt"
    cli.cmd_check_updates(_args(output_file=str(out_file)))

    assert out_file.read_text(encoding="utf-8") == "alpha==2.0\n"


def test_check_updates_output_file_dash_writes_to_stdout(monkeypatch, capsys):
    def fake_pip_list_json(extra_args, timeout):
        if extra_args == ["--outdated"]:
            return [{"name": "alpha", "version": "1.0", "latest_version": "2.0"}]
        return [{"name": "alpha", "version": "1.0"}]

    monkeypatch.setattr(cli, "_pip_list_json", fake_pip_list_json)

    cli.cmd_check_updates(_args(output_file="-"))

    out, err = capsys.readouterr()
    assert out == "alpha==2.0\n"
    # the table itself is redirected to stderr so stdout stays parseable
    assert "alpha" in err


def test_check_updates_no_output_file_when_nothing_outdated(monkeypatch, tmp_path, capsys):
    def fake_pip_list_json(extra_args, timeout):
        return [] if extra_args == ["--outdated"] else [{"name": "alpha", "version": "1.0"}]

    monkeypatch.setattr(cli, "_pip_list_json", fake_pip_list_json)

    out_file = tmp_path / "updates.txt"
    cli.cmd_check_updates(_args(output_file=str(out_file)))

    assert not out_file.exists()
    out, _ = capsys.readouterr()
    assert "not written" in out


def test_check_updates_include_install_date_column(monkeypatch, tmp_path, capsys):
    dist_info = tmp_path / "alpha.dist-info"
    dist_info.write_text("x")

    fake_dist = types.SimpleNamespace(metadata={"Name": "alpha"}, _path=dist_info)

    def fake_pip_list_json(extra_args, timeout):
        return [] if extra_args == ["--outdated"] else [{"name": "alpha", "version": "1.0"}]

    monkeypatch.setattr(cli, "_pip_list_json", fake_pip_list_json)
    monkeypatch.setattr(cli, "distributions", lambda: [fake_dist])

    cli.cmd_check_updates(_args(include_install_date=True))

    out, _ = capsys.readouterr()
    assert "Installed on" in out
