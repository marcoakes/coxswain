"""CLI surface smoke tests."""

import subprocess
import sys

from wringer import __version__, cli


def test_version_flag_reports_package_version(capsys):
    try:
        cli.main(["--version"])
    except SystemExit as exc:  # argparse's version action exits 0
        assert exc.code == 0
    out = capsys.readouterr().out
    assert out.strip() == f"wring {__version__}"


def test_python_dash_m_wringer_help_works():
    proc = subprocess.run(
        [sys.executable, "-m", "wringer", "--help"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0
    assert "usage: wring" in proc.stdout
