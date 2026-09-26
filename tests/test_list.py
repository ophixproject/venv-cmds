import types
from importlib.metadata import entry_points

from venv_cmds import cli


def test_console_scripts_exist():
    eps = entry_points(group="console_scripts")
    names = {ep.name for ep in eps}

    # pip should always exist in a venv
    assert "pip" in names


class _FakeDist:
    def __init__(self, name):
        self.metadata = {"Name": name}


class _FakeEntryPoint:
    def __init__(self, name, dist=None):
        self.name = name
        self.dist = dist


def _fake_entry_points(monkeypatch, eps):
    monkeypatch.setattr(cli, "entry_points", lambda group=None: eps)


def test_cmd_list_plain_sorted(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_in_venv", lambda: False)
    _fake_entry_points(monkeypatch, [
        _FakeEntryPoint("zeta"),
        _FakeEntryPoint("alpha"),
    ])

    cli.cmd_list(types.SimpleNamespace(details=False))

    out, err = capsys.readouterr()
    assert out.splitlines() == ["alpha", "zeta"]
    assert "Warning" in err


def test_cmd_list_details_shows_package_name(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_in_venv", lambda: False)
    _fake_entry_points(monkeypatch, [
        _FakeEntryPoint("thing", dist=_FakeDist("thing-package")),
    ])

    cli.cmd_list(types.SimpleNamespace(details=True))

    out, _ = capsys.readouterr()
    assert out.strip() == "thing (package: thing-package)"


def test_cmd_list_details_unknown_package_when_no_dist(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_in_venv", lambda: False)
    _fake_entry_points(monkeypatch, [_FakeEntryPoint("orphan", dist=None)])

    cli.cmd_list(types.SimpleNamespace(details=True))

    out, _ = capsys.readouterr()
    assert out.strip() == "orphan (package: unknown)"


def test_cmd_list_in_venv_prints_info(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_in_venv", lambda: True)
    monkeypatch.setattr(cli, "_venv_name", lambda: "myenv")
    _fake_entry_points(monkeypatch, [])

    cli.cmd_list(types.SimpleNamespace(details=False))

    out, _ = capsys.readouterr()
    assert "detected virtual environment 'myenv'" in out
