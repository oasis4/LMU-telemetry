"""Debug script to examine lap time detection and validity issues."""
import sys, os, glob
import duckdb
import numpy as np

TDIR = os.environ.get("TELEMETRY_DIR", r"F:\SteamLibrary\steamapps\common\Le Mans Ultimate\UserData\Telemetry")

files = sorted(glob.glob(os.path.join(TDIR, "*.duckdb")))
if not files:
    print("No files found in", TDIR)
    sys.exit(1)

# Pick the latest file (most recent session)
fpath = files[-1]
# Also test with a race file if available
practice_files = [f for f in files if '_P_' in os.path.basename(f)]
if practice_files:
    fpath = practice_files[-1]
    print(f"=== Analyzing: {os.path.basename(fpath)} ===\n")

conn = duckdb.connect(fpath, read_only=True)

# 1. Check Lap event table
print("--- Lap Events ---")
try:
    df = conn.execute('SELECT ts, value FROM "Lap" ORDER BY ts').fetchdf()
    print(f"  {len(df)} events")
    for _, row in df.iterrows():
        print(f"  ts={row['ts']:.2f}  lap={int(row['value'])}")
except Exception as e:
    print(f"  ERROR: {e}")

# 2. Check LapTime event table
print("\n--- LapTime Events ---")
for tbl in ["Current LapTime", "Lap Time"]:
    try:
        df = conn.execute(f'SELECT ts, value FROM "{tbl}" ORDER BY ts').fetchdf()
        print(f"  Table '{tbl}': {len(df)} events")
        for _, row in df.iterrows():
            secs = row['value']
            mins = int(secs // 60)
            remainder = secs - mins * 60
            print(f"  ts={row['ts']:.2f}  time={secs:.3f}s ({mins}:{remainder:06.3f})")
        break
    except Exception:
        continue

# 3. Check Sector events
print("\n--- Sector1 Events ---")
try:
    df = conn.execute('SELECT ts, value FROM "Current Sector1" ORDER BY ts').fetchdf()
    print(f"  {len(df)} events")
    for _, row in df.iterrows():
        print(f"  ts={row['ts']:.2f}  s1={row['value']:.3f}s")
except Exception as e:
    print(f"  ERROR: {e}")

print("\n--- Sector2 Events (cumulative S1+S2) ---")
try:
    df = conn.execute('SELECT ts, value FROM "Current Sector2" ORDER BY ts').fetchdf()
    print(f"  {len(df)} events")
    for _, row in df.iterrows():
        print(f"  ts={row['ts']:.2f}  s1+s2={row['value']:.3f}s")
except Exception as e:
    print(f"  ERROR: {e}")

# 4. GPS Time range
print("\n--- GPS Time Range ---")
try:
    df = conn.execute('SELECT MIN(value) as tmin, MAX(value) as tmax FROM "GPS Time"').fetchdf()
    print(f"  min={df['tmin'].iloc[0]:.2f}  max={df['tmax'].iloc[0]:.2f}  span={df['tmax'].iloc[0]-df['tmin'].iloc[0]:.2f}s")
except Exception as e:
    print(f"  ERROR: {e}")

# 5. Now run the actual LapProcessor and show results
print("\n--- LapProcessor Output ---")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backend.duckdb_reader import DuckDBSession
from backend.lap_processor import LapProcessor

sess = DuckDBSession(fpath)
proc = LapProcessor(sess)
laps = proc.process()

print(f"  {len(laps)} laps detected")
for l in laps:
    ms = l.lap_time_ms
    mins = int(ms // 60000)
    secs = (ms % 60000) / 1000
    sectors_str = ""
    if l.sectors:
        sectors_str = " sectors=[" + ", ".join(f"{s/1000:.3f}s" for s in l.sectors) + "]"
        sectors_str += f" matched={l.sectors_matched}"
    print(f"  Lap {l.lap_number:>2}: {mins}:{secs:06.3f}  valid={l.valid}  dist={l.distance[-1]:.0f}m{sectors_str}")

# 6. Check if there's an InvalidLap or similar table
print("\n--- Checking for invalidity-related tables ---")
try:
    tables = conn.execute("SELECT table_name FROM information_schema.tables WHERE table_type = 'BASE TABLE'").fetchall()
    invalid_tables = [t[0] for t in tables if 'invalid' in t[0].lower() or 'penalty' in t[0].lower() or 'cut' in t[0].lower() or 'flag' in t[0].lower()]
    if invalid_tables:
        for t in invalid_tables:
            df = conn.execute(f'SELECT * FROM "{t}"').fetchdf()
            print(f"  Table '{t}': {len(df)} rows")
            print(f"    columns: {list(df.columns)}")
            if len(df) > 0:
                print(df.to_string(index=False))
    else:
        # Search more broadly
        for t in [t[0] for t in tables]:
            tl = t.lower()
            if any(kw in tl for kw in ['lap', 'valid', 'status']):
                try:
                    cnt = conn.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                    cols = conn.execute(f'PRAGMA table_info("{t}")').fetchall()
                    col_names = [c[1] for c in cols]
                    print(f"  '{t}': {cnt} rows, cols={col_names}")
                except:
                    pass
except Exception as e:
    print(f"  ERROR: {e}")

conn.close()
sess.close()
