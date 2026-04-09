"""
Cleanup-Skript: Löscht kaputte/nutzlose DuckDB-Telemetrie-Dateien.
- Leere Dateien (0 Bytes)
- Dateien mit 0–2 Runden (Out-Lap, Abbrüche, etc.)
"""

import os
import sys
import glob
import duckdb

# Standard-Telemetrie-Verzeichnis
DEFAULT_DIR = r"F:\SteamLibrary\steamapps\common\Le Mans Ultimate\UserData\Telemetry"


def count_laps(filepath):
    """Zählt die Runden in einer DuckDB-Datei. Gibt -1 bei Fehler zurück."""
    try:
        conn = duckdb.connect(str(filepath), read_only=True)
        tables = [r[0] for r in conn.execute("SHOW TABLES").fetchall()]
        if "Lap" not in tables:
            conn.close()
            return 0
        result = conn.execute('SELECT MAX(value) FROM "Lap"').fetchone()
        conn.close()
        if result and result[0] is not None:
            return int(result[0])
        return 0
    except Exception as e:
        print(f"  FEHLER beim Lesen: {e}")
        return -1


def format_size(size_bytes):
    """Dateigröße lesbar formatieren."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.1f} MB"


def main():
    telemetry_dir = os.environ.get("TELEMETRY_DIR", DEFAULT_DIR)

    if len(sys.argv) > 1:
        telemetry_dir = sys.argv[1]

    if not os.path.isdir(telemetry_dir):
        print(f"Verzeichnis nicht gefunden: {telemetry_dir}")
        print("Nutzung: python cleanup_sessions.py [Pfad zum Telemetrie-Ordner]")
        sys.exit(1)

    files = glob.glob(os.path.join(telemetry_dir, "*.duckdb"))
    if not files:
        print(f"Keine .duckdb-Dateien in: {telemetry_dir}")
        sys.exit(0)

    print(f"Scanne {len(files)} Dateien in: {telemetry_dir}\n")

    to_delete = []  # (filepath, reason, size)
    kept = 0

    for filepath in sorted(files):
        name = os.path.basename(filepath)
        size = os.path.getsize(filepath)

        if size == 0:
            to_delete.append((filepath, "Leer (0 Bytes)", size))
            print(f"  LÖSCHEN  {name}  —  Leer (0 Bytes)")
            continue

        laps = count_laps(filepath)

        if laps < 0:
            to_delete.append((filepath, "Kaputt (nicht lesbar)", size))
            print(f"  LÖSCHEN  {name}  —  Kaputt ({format_size(size)})")
        elif laps <= 2:
            to_delete.append((filepath, f"{laps} Runde(n)", size))
            print(f"  LÖSCHEN  {name}  —  {laps} Runde(n) ({format_size(size)})")
        else:
            kept += 1
            print(f"  OK       {name}  —  {laps} Runden ({format_size(size)})")

    print(f"\n{'=' * 60}")
    total_size = sum(s for _, _, s in to_delete)
    print(f"Ergebnis: {len(to_delete)} Dateien zum Löschen ({format_size(total_size)}), {kept} behalten")

    if not to_delete:
        print("Nichts zu tun!")
        sys.exit(0)

    print()
    answer = input("Wirklich löschen? (j/n): ").strip().lower()
    if answer != "j":
        print("Abgebrochen.")
        sys.exit(0)

    deleted = 0
    freed = 0
    for filepath, reason, size in to_delete:
        try:
            os.remove(filepath)
            # Auch .wal-Datei löschen falls vorhanden
            wal = filepath + ".wal"
            if os.path.exists(wal):
                os.remove(wal)
            deleted += 1
            freed += size
            print(f"  Gelöscht: {os.path.basename(filepath)}")
        except Exception as e:
            print(f"  FEHLER beim Löschen von {os.path.basename(filepath)}: {e}")

    print(f"\n{deleted} Dateien gelöscht, {format_size(freed)} freigegeben.")


if __name__ == "__main__":
    main()
