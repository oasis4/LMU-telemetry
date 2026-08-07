import pytest

from lmu_telemetry.core.session import Session


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


def test_no_track_length_without_a_complete_lap(no_complete_lap_file):
    """160 m of an abandoned out-lap is not the length of Monza."""
    with Session.open(no_complete_lap_file) as s:
        assert s.laps == []
        assert s.track_length_m is None


def test_fastest_lap_excludes_the_out_lap(monza_q_file):
    with Session.open(monza_q_file) as s:
        fastest = s.fastest_lap
    assert fastest is not None
    assert fastest.number == 2
    assert fastest.duration_s == pytest.approx(111.000)


@pytest.mark.corpus
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
        # Lap 0 is not a lap time - it is however much of a lap the recording
        # happened to catch. One Sebring session offers 43.3 s of a 5820 m
        # circuit, so a fastest lap that is lap 0 is the impossible-time
        # defect itself.
        assert fastest.number > 0, f"{path.name}: fastest lap is lap 0"
        # No car in any class averages more than 300 km/h over a full lap.
        floor = length / (300.0 / 3.6)
        assert fastest.duration_s > floor, (
            f"{path.name}: {fastest.duration_s:.2f}s over {length:.0f}m "
            f"implies more than 300 km/h average"
        )
        checked += 1
    assert checked >= 0.8 * len(corpus_files), (
        f"only {checked} of {len(corpus_files)} sessions reported a fastest lap"
    )
