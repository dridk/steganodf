import pytest

import steganodf as st
from steganodf.__main__ import parse_cli


def test_version_flag_prints_the_installed_version(capsys):
    with pytest.raises(SystemExit) as exit_info:
        parse_cli(["--version"])

    assert exit_info.value.code == 0
    assert capsys.readouterr().out.strip() == f"steganodf {st.__version__}"


def test_version_short_flag(capsys):
    with pytest.raises(SystemExit):
        parse_cli(["-V"])

    assert capsys.readouterr().out.startswith("steganodf ")


def test_version_is_the_packaged_one():
    # "unknown" means importlib.metadata could not find the distribution, which
    # would make the flag useless for anyone reporting a bug.
    assert st.__version__ != "unknown"
