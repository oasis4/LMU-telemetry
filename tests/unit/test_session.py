import pytest

from lmu_telemetry.core.session import Session

pytestmark = pytest.mark.corpus


def test_info_is_read_from_metadata(monza_q_file):
    with Session.open(monza_q_file) as s:
        info = s.info
    assert info.track == "Autodromo Nazionale Monza"
    assert info.layout == "Autodromo Nazionale Monza"
    assert info.car_class == "GT3"
    assert info.driver == "A Mueller"
    assert info.session_type == "Qualify"


def test_track_length_is_the_maximum_lap_distance(monza_q_file):
    with Session.open(monza_q_file) as s:
        assert s.track_length_m == pytest.approx(5776.08, abs=0.1)


def test_fastest_lap_excludes_the_out_lap(monza_q_file):
    with Session.open(monza_q_file) as s:
        fastest = s.fastest_lap
    assert fastest is not None
    assert fastest.number == 2
    assert fastest.duration_s == pytest.approx(111.000)


def test_every_corpus_session_reports_plausible_fastest_lap(corpus_files):
    """Nothing in the corpus may look like a world record.

    Ranges are the known real-world envelope per track length, deliberately
    generous: the point is to catch fabricated times, not to grade driving.
    """
    checked = 0
    for path in corpus_files:
        with Session.open(path) as s:
            fastest = s.fastest_lap
            length = s.track_length_m
        if fastest is None:
            continue
        # No car in any class averages more than 300 km/h over a full lap.
        floor = length / (300.0 / 3.6)
        assert fastest.duration_s > floor, (
            f"{path.name}: {fastest.duration_s:.2f}s over {length:.0f}m "
            f"implies more than 300 km/h average"
        )
        checked += 1
    assert checked == 32, f"expected 32 sessions with a fastest lap, checked {checked}"
