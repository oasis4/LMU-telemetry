"""The corpus fixtures must find the real telemetry files, or skip cleanly."""

import pytest

pytestmark = pytest.mark.corpus


def test_corpus_files_are_duckdb(corpus_files):
    assert len(corpus_files) >= 1
    assert all(f.suffix == ".duckdb" for f in corpus_files)


def test_monza_reference_file_exists(monza_q_file):
    assert monza_q_file.is_file()
    assert monza_q_file.name.startswith("Autodromo Nazionale Monza_Q_2026-03-28T17_02_56Z")
