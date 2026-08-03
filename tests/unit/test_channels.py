import numpy as np
import pytest

from lmu_telemetry.io.channels import (
    ChannelRegistry,
    ChannelSpec,
    MissingChannelError,
    normalise,
)


def test_percent_channel_is_scaled_to_fraction():
    spec = ChannelSpec(name="Throttle Pos", frequency_hz=50, unit="%")
    out = normalise(np.array([0.0, 50.0, 100.0]), spec)
    assert np.allclose(out, [0.0, 0.5, 1.0])


def test_percent_scaling_uses_100_not_observed_maximum():
    """A lap where the driver never reached full lock must NOT be stretched.

    One Le Mans session has |Steering Pos| max 93.023 with unit '%'.
    Dividing by the observed maximum would report 93% lock as 100%.
    """
    spec = ChannelSpec(name="Steering Pos", frequency_hz=100, unit="%")
    out = normalise(np.array([-93.023, 0.0, 46.5]), spec)
    assert np.isclose(out[0], -0.93023)
    assert np.isclose(out[2], 0.465)


def test_unitless_channel_is_passed_through():
    spec = ChannelSpec(name="Steering Pos", frequency_hz=100, unit="")
    values = np.array([-0.8085, 0.0, 0.5079])
    out = normalise(values, spec)
    assert np.allclose(out, values)


def test_metre_channel_is_passed_through():
    spec = ChannelSpec(name="Lap Dist", frequency_hz=10, unit="m")
    values = np.array([0.0, 2887.5, 5775.0])
    assert np.allclose(normalise(values, spec), values)


def test_normalise_does_not_mutate_input():
    spec = ChannelSpec(name="Brake Pos", frequency_hz=50, unit="%")
    values = np.array([100.0])
    normalise(values, spec)
    assert values[0] == 100.0


@pytest.mark.corpus
def test_registry_reads_real_channel_list(monza_q_file):
    import duckdb

    con = duckdb.connect(str(monza_q_file), read_only=True)
    try:
        reg = ChannelRegistry.from_connection(con)
    finally:
        con.close()

    assert reg.require("Ground Speed") == ChannelSpec("Ground Speed", 100, "km/h")
    assert reg.require("Lap Dist") == ChannelSpec("Lap Dist", 10, "m")
    assert reg.require("Throttle Pos") == ChannelSpec("Throttle Pos", 50, "%")
    assert reg.require("Brake Pos") == ChannelSpec("Brake Pos", 50, "%")
    assert reg.require("GPS Speed") == ChannelSpec("GPS Speed", 10, "m/s")
    assert reg.require("GPS Time") == ChannelSpec("GPS Time", 100, "s")
    assert "Lap" not in reg  # events are not channels
    assert len(reg.names()) == 56


@pytest.mark.corpus
def test_require_raises_for_unknown_channel(monza_q_file):
    import duckdb

    con = duckdb.connect(str(monza_q_file), read_only=True)
    try:
        reg = ChannelRegistry.from_connection(con)
    finally:
        con.close()
    with pytest.raises(MissingChannelError):
        reg.require("No Such Channel")
