"""Channel metadata read from the file's own ``channelsList`` table.

Every LMU telemetry file declares, for each continuous channel, its sampling
frequency and its unit.  Reading that table is the difference between knowing
that ``Brake Pos`` is a percentage and guessing that it is a 0..1 fraction.

The unit genuinely varies between files: ``Steering Pos`` is reported unitless
(range +-1) in most sessions and as a percentage (range +-100) in others.  The
unit column is the only reliable discriminator - the observed value range is
not, because a driver who never reaches full lock produces a smaller maximum.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


class MissingChannelError(KeyError):
    """Raised when a required channel is absent from the file."""


@dataclass(frozen=True)
class ChannelSpec:
    """Declared properties of one continuous channel."""

    name: str
    frequency_hz: int
    unit: str


#: Unit -> factor applied to convert into the canonical representation.
#: Percentages become 0..1 fractions.  Everything else is already canonical.
_UNIT_FACTORS: dict[str, float] = {"%": 0.01}


def normalise(values: np.ndarray, spec: ChannelSpec) -> np.ndarray:
    """Convert *values* into canonical units for *spec*.

    Returns a new array; the input is never modified.
    """
    factor = _UNIT_FACTORS.get(spec.unit)
    if factor is None:
        return np.asarray(values, dtype=np.float64).copy()
    return np.asarray(values, dtype=np.float64) * factor


class ChannelRegistry:
    """Lookup of :class:`ChannelSpec` by channel name."""

    def __init__(self, specs: dict[str, ChannelSpec]) -> None:
        self._specs = specs

    @classmethod
    def from_connection(cls, con) -> "ChannelRegistry":
        rows = con.execute(
            'SELECT channelName, frequency, unit FROM "channelsList"'
        ).fetchall()
        specs = {
            str(name): ChannelSpec(
                name=str(name),
                frequency_hz=int(freq),
                unit="" if unit is None else str(unit),
            )
            for name, freq, unit in rows
        }
        return cls(specs)

    def get(self, name: str) -> ChannelSpec | None:
        return self._specs.get(name)

    def require(self, name: str) -> ChannelSpec:
        spec = self._specs.get(name)
        if spec is None:
            raise MissingChannelError(name)
        return spec

    def __contains__(self, name: object) -> bool:
        return name in self._specs

    def names(self) -> list[str]:
        return sorted(self._specs)
