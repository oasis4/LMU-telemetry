"""The corpus fixtures must find the real telemetry files, or skip cleanly."""

import pytest


@pytest.mark.corpus
def test_corpus_files_are_duckdb(corpus_files):
    assert len(corpus_files) >= 1
    assert all(f.suffix == ".duckdb" for f in corpus_files)


def test_reference_session_resolves_to_a_readable_file(monza_q_file):
    """Resolves to the committed fixture, or the corpus original as a fallback."""
    assert monza_q_file.is_file()
    assert monza_q_file.suffix == ".duckdb"
