"""Build interpreter validation runs from a file under Windows PowerShell 5.1."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    'check_python', Path(__file__).resolve().parents[2] / 'packaging/check-python.py')
check = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check)


@pytest.mark.parametrize('version,bits', [((3, 14), 8), ((3, 12), 8), ((3, 13), 4)])
def test_rejects_incompatible_build_interpreters(monkeypatch, capsys, version, bits):
    monkeypatch.setattr(check.sys, 'version_info', version)
    monkeypatch.setattr(check.struct, 'calcsize', lambda fmt: bits)
    assert check.main() == 1
    assert 'Python 3.13 x64 required' in capsys.readouterr().err


def test_selects_exact_interpreter_path_for_venv(monkeypatch, capsys):
    monkeypatch.setattr(check.sys, 'version_info', (3, 13))
    monkeypatch.setattr(check.struct, 'calcsize', lambda fmt: 8)
    monkeypatch.setattr(check.sys, 'executable', r'C:\Python 3.13\python.exe')
    assert check.main() == 0
    assert capsys.readouterr().out.strip() == r'C:\Python 3.13\python.exe'
