from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_XLSX = ROOT / "data" / "raw" / "PeoplePulse_IBM_Integrated.xlsx"
STAGE = ROOT / "data" / "staging"
SYN = ROOT / "data" / "synthetic"
PROC = ROOT / "data" / "processed"
SQL = ROOT / "sql"
OUT = ROOT / "outputs"
CHARTS = OUT / "charts"
DB = ROOT / "data" / "peoplepulse.duckdb"

SNAPSHOT_DATE = "2026-09-30"
SEED = 42

for p in (STAGE, SYN, PROC, OUT, CHARTS):
    p.mkdir(parents=True, exist_ok=True)
