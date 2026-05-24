from importlib.metadata import entry_points

def test_console_scripts_exist():
    eps = entry_points(group="console_scripts")
    names = {ep.name for ep in eps}

    # pip should always exist in a venv
    assert "pip" in names