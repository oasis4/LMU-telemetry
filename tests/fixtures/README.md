# Test fixtures

Real telemetry, cut down for version control by `tools/build_fixtures.py`.

Each file keeps only the tables the tests read, blanks the `CarSetup` JSON blob
and uses a 16 kB DuckDB block size. Channel values, event timestamps and
`channelsList` entries are untouched, so assertions made against the full
corpus hold here too.

| Fixture | Why it exists |
|---|---|
| `monza_q_3laps.duckdb` | Reference session. 3 complete laps: 131.085 / 116.560 / 111.000 s. |
| `monza_q_no_complete_lap.duckdb` | Abandoned after 160 m. One `Lap` event, so no lap is bounded on both sides. |
| `lemans_r_percent_steering.duckdb` | `Steering Pos` carries unit `%` (range ±100) rather than the usual ±1. |
| `monza_r_extra_dist_reset.duckdb` | 12 `Lap` events but 13 `Lap Dist` resets — the case that produced impossible lap times in the old implementation. |

Rebuild with `python tools/build_fixtures.py` (needs the local corpus).
