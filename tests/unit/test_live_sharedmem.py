"""What can be checked without the game: that the transcription is coherent,
and that absence is loud.

The struct layout itself can only be confirmed against the running game - the
mapping's size is the check, and it is in LiveTelemetry.__init__. What is
testable here is that the fields the buffer needs exist under the names it
uses, and that a missing mapping is an error rather than a stream of zeros.
"""

import ctypes

import pytest

from lmu_telemetry.live import sharedmem


def test_a_missing_mapping_says_what_is_wrong():
    """A reader that returned zeros would drive a panel that confidently
    showed a stationary car sitting on the start line."""
    original = sharedmem.MAPPING
    sharedmem.MAPPING = "$LMU_Data_that_does_not_exist$"
    try:
        with pytest.raises(sharedmem.SharedMemoryUnavailable) as caught:
            sharedmem.LiveTelemetry()
    finally:
        sharedmem.MAPPING = original
    assert "Le Mans Ultimate" in str(caught.value)


def test_the_telemetry_struct_carries_what_a_sample_needs():
    names = {name for name, *_ in sharedmem._TelemInfo._fields_}
    for needed in ("mLapDist_is_not_here", ):
        assert needed not in names, "lap distance is on the scoring side"
    for needed in ("mElapsedTime", "mLapStartET", "mLapNumber", "mLocalVel",
                   "mUnfilteredThrottle", "mUnfilteredBrake",
                   "mUnfilteredSteering", "mID"):
        assert needed in names, needed


def test_lap_distance_is_on_the_scoring_side():
    """The whole reason distance has to be anchored and carried: it arrives at
    about 5 Hz with scoring, not at 50 Hz with telemetry."""
    telemetry = {name for name, *_ in sharedmem._TelemInfo._fields_}
    scoring = {name for name, *_ in sharedmem._VehicleScoring._fields_}
    assert "mLapDist" not in telemetry
    assert "mLapDist" in scoring
    assert "mIsPlayer" in scoring


def test_the_v01_structs_are_packed_to_four():
    """InternalsPlugin.hpp wraps them in #pragma pack(push, 4). Left at
    natural alignment every double after the first odd-sized field lands
    eight bytes late, and every value read past it is plausible and wrong."""
    for struct in (sharedmem._Vec3, sharedmem._TelemWheel, sharedmem._TelemInfo,
                   sharedmem._VehicleScoring, sharedmem._ScoringInfo,
                   sharedmem._AppState):
        assert getattr(struct, "_pack_", None) == 4, struct.__name__


def test_the_wrapper_structs_are_not_packed():
    """They come from SharedMemoryInterface.hpp, after the matching pop."""
    for struct in (sharedmem._Generic, sharedmem._PathData,
                   sharedmem._ScoringData, sharedmem._TelemetryData,
                   sharedmem._ObjectOut):
        assert getattr(struct, "_pack_", 0) in (0, None), struct.__name__


def test_the_early_field_offsets_are_the_ones_the_header_implies():
    """Hand-computable from InternalsPlugin.hpp, and the proof pack(4) took.

    At natural alignment mDeltaTime - a double after a 4-byte long - would sit
    at 8 rather than 4, and every field after it would be four bytes out. That
    does not fail: it returns doubles assembled from the tail of one value and
    the head of the next, which are finite, plausible numbers.
    """
    telem = sharedmem._TelemInfo
    assert telem.mID.offset == 0
    assert telem.mDeltaTime.offset == 4          # 8 if the packing were lost
    assert telem.mElapsedTime.offset == 12
    assert telem.mLapNumber.offset == 20
    assert telem.mLapStartET.offset == 24
    assert telem.mVehicleName.offset == 32
    assert telem.mTrackName.offset == 96         # 32 + 64
    assert telem.mPos.offset == 160              # 96 + 64

    scoring = sharedmem._VehicleScoring
    assert scoring.mID.offset == 0
    assert scoring.mDriverName.offset == 4
    assert scoring.mVehicleName.offset == 36     # 4 + 32
    assert scoring.mTotalLaps.offset == 100      # 36 + 64
    assert scoring.mLapDist.offset == 104        # short + 2 bytes, then double


def test_the_layout_is_built_from_its_parts_without_slack():
    """A field dropped from one of the per-car structs would shrink the whole
    layout by 104 times its size, and the mapping check at open would catch
    it - but only with the game running. This catches the arithmetic here."""
    per_car = ctypes.sizeof(sharedmem._TelemInfo)
    per_scoring = ctypes.sizeof(sharedmem._VehicleScoring)
    total = ctypes.sizeof(sharedmem._ObjectOut)

    floor = (
        sharedmem.MAX_VEHICLES * (per_car + per_scoring)
        + 65536                                   # the results stream
    )
    assert floor < total < floor + 4096, (floor, total)


def test_the_player_is_found_by_id_and_not_by_index():
    """Telemetry is indexed by the game's playerVehicleIdx and scoring by
    finishing order, so the same slot in each is not the same car."""
    state = sharedmem._ObjectOut()
    state.scoring.scoringInfo.mNumVehicles = 3
    state.scoring.vehScoringInfo[0].mID = 11
    state.scoring.vehScoringInfo[1].mID = 22
    state.scoring.vehScoringInfo[2].mID = 33

    found = sharedmem.LiveTelemetry._player_scoring(state, 22)
    assert found is not None and found.mID == 22
    assert sharedmem.LiveTelemetry._player_scoring(state, 99) is None


# -- opening the mapping ---------------------------------------------------


def test_a_named_mapping_is_found_only_while_it_exists():
    """The probe that lets the two failures be told apart.

    "The game is not running" and "the game is running and these structs are
    the wrong size" need different fixes, and a single failure that blames the
    game for both sends the reader off to restart something that was fine.
    """
    import mmap

    name = "lmu_telemetry_test_mapping"
    assert not sharedmem.mapping_exists(name), "left over from an earlier run"

    holder = mmap.mmap(-1, 4096, name)
    try:
        assert sharedmem.mapping_exists(name)
    finally:
        holder.close()
    assert not sharedmem.mapping_exists(name)


def test_mmap_creates_where_this_must_only_open():
    """Why the reader uses OpenFileMapping and not mmap.

    ``mmap.mmap(-1, n, name)`` does not open a named mapping, it *creates*
    one. Pointed at a name nothing is publishing it succeeds and hands back a
    page of zeros - and a reader built on that shows a stationary car sitting
    confidently on the start line instead of saying the game is not running.

    This asserts the trap is real, so that anyone tempted back to mmap for
    being tidier can see what it costs.
    """
    import mmap

    name = "lmu_telemetry_nothing_publishes_this"
    assert not sharedmem.mapping_exists(name)

    invented = mmap.mmap(-1, 4096, name, access=mmap.ACCESS_WRITE)
    try:
        assert invented[:16] == b"\x00" * 16, "zeros, out of thin air"
    finally:
        invented.close()


def test_the_game_being_absent_does_not_read_as_a_wrong_transcription():
    """Whichever it is, the reader is told which."""
    if sharedmem.mapping_exists(sharedmem.MAPPING):
        pytest.skip("the game is running, so the absent case cannot be made")

    with pytest.raises(sharedmem.SharedMemoryUnavailable) as raised:
        sharedmem.LiveTelemetry()
    said = str(raised.value)
    assert "must be running" in said
    assert "re-transcribe" not in said.lower(), (
        "an absent game was reported as a struct mismatch"
    )
