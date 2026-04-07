"""Debug: inspect lap data from a Portimao session."""
from backend.duckdb_reader import DuckDBSession
from backend.lap_processor import LapProcessor
import os

tdir = r'F:/SteamLibrary/steamapps/common/Le Mans Ultimate/UserData/Telemetry'
files = [f for f in os.listdir(tdir) if 'Algarve' in f and f.endswith('.duckdb')]
print(f'Found {len(files)} Algarve files')
if files:
    fn = files[-1]
    print(f'Using: {fn}')
    sess = DuckDBSession(os.path.join(tdir, fn))
    proc = LapProcessor(sess)
    laps = proc.process()
    print(f'Total laps: {len(laps)}')
    for l in laps:
        secs = [f'{s:.0f}' for s in l.sectors] if l.sectors else []
        t_sec = l.lap_time_ms / 1000
        m = int(t_sec) // 60
        s = t_sec - m * 60
        print(f'  Lap {l.lap_number:2d}: {m}:{s:06.3f}  ({l.lap_time_ms:.0f}ms)  valid={l.valid}  sectors_ms={secs}')

    valid = [l for l in laps if l.valid and l.lap_time_ms > 0]
    print(f'\nValid laps: {len(valid)}')
    if valid:
        fastest = min(l.lap_time_ms for l in valid)
        t_sec = fastest / 1000
        m = int(t_sec) // 60
        s = t_sec - m * 60
        print(f'Fastest valid: {m}:{s:06.3f}')

    # Theoretical best sectors
    source = valid if valid else laps
    n_sectors = max((len(l.sectors) for l in source), default=0)
    best_sectors = []
    for si in range(n_sectors):
        vals = sorted([l.sectors[si] for l in source if si < len(l.sectors) and l.sectors[si] > 0])
        if vals:
            median = vals[len(vals) // 2]
            print(f'  Sector {si+1}: min={vals[0]:.0f}ms  median={median:.0f}ms  values={[f"{v:.0f}" for v in vals]}')
            # Filter out < 70% of median
            filtered = [v for v in vals if v >= median * 0.7]
            best = min(filtered) if filtered else vals[0]
            best_sectors.append(best)
        else:
            best_sectors.append(0)
    
    if best_sectors:
        theo = sum(best_sectors)
        t_sec = theo / 1000
        m = int(t_sec) // 60
        s = t_sec - m * 60
        print(f'\nTheoretical best: {m}:{s:06.3f}  (sectors: {[f"{s:.0f}" for s in best_sectors]})')
