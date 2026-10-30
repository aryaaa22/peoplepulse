"""Phase 1c: build the DuckDB star schema and KPI views from the SQL files."""
import duckdb

from config import DB, SNAPSHOT_DATE, SQL, STAGE, SYN

FILES = ["01_staging.sql", "02_dimensions.sql", "03_facts.sql", "04_kpi_views.sql"]


def main():
    DB.unlink(missing_ok=True)
    con = duckdb.connect(str(DB))
    for f in FILES:
        sql = (SQL / f).read_text().replace("{stage}", str(STAGE)).replace("{syn}", str(SYN)).replace("{snapshot}", SNAPSHOT_DATE)
        con.execute(sql)
        print("ran", f)
    for (t,) in con.execute("SELECT table_name FROM information_schema.tables ORDER BY 1").fetchall():
        print(f"  {t}: {con.execute(f'SELECT count(*) FROM {t}').fetchone()[0]:,}")
    print(con.execute("SELECT * FROM vw_kpi_overall").df().T.to_string())
    con.close()


if __name__ == "__main__":
    main()
