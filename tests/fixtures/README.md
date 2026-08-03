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
| `monza_r_extra_dist_reset.duckdb` | Truncated to the first 700 s of a session whose full recording has more `Lap Dist` resets than `Lap` events; the shipped fixture keeps 6 of each, with one reset that does not line up with a `Lap` event gap — the same mismatch that produced impossible lap times in the old implementation. |
| `imola_r_unclosed_lap.duckdb` | Truncated to the first 500 s of an Imola race, keeping lap 0 (315.82 s, formation lap fused with the first racing lap, distance ratio 1.93) and lap 1 (118.40 s) complete. Its only complete racing lap closes at 406°, not 360°, so the track legitimately yields no reference model — exercises both the distance-ratio and closure-band rejection branches in `assess_lap`. |

Rebuild with `python tools/build_fixtures.py` (needs the local corpus).
