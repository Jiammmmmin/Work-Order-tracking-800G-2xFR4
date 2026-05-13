"""
MES Schema Explorer
Run once: python explore_schema.py
Outputs:  schema_log.txt  (human-readable)
          schema_columns.json  (machine-readable for future reference)

Edit SAMPLE_* constants below if you have a different sample WO.
"""

import pyodbc
import json
import os
from datetime import datetime, date, time
from decimal import Decimal

# ── Connection ────────────────────────────────────────────────────────────────
CONN_STR = (
    r"DRIVER=SQL Server;"
    r"SERVER=US_SQL01.USPL.HOME;"
    r"DATABASE=MES;"
    r"UID=LABVIEW;"
    r"PWD=LABVIEW;"
)

# ── Sample identifiers (adjust if needed) ─────────────────────────────────────
SAMPLE_WO          = "120052817"
SAMPLE_LOT         = "12005281702"
SAMPLE_WPC_WO_SID  = "A2026042211464770844"
SAMPLE_WIP_COMP_SID = "A2026042413490658513"

# ── Tables to explore ─────────────────────────────────────────────────────────
# (display_name, sql_schema, sql_table, sample_WHERE_clause)
# sql_schema=None → INFORMATION_SCHEMA lookup skipped (e.g. views)
TABLES = [
    ("v_MasterWOInfo",            None,    "v_MasterWOInfo",              f"WO = '{SAMPLE_WO}'"),
    ("MES_WPC_WO",                "dbo",   "MES_WPC_WO",                  f"WO = '{SAMPLE_WO}'"),
    ("AOI_WO_RUNCARD",            "dbo",   "AOI_WO_RUNCARD",              f"WPC_WO_SID = '{SAMPLE_WPC_WO_SID}'"),
    ("MES_WIP_LOT",               "dbo",   "MES_WIP_LOT",                 f"WO = '{SAMPLE_WO}'"),
    ("MES_WIP_LOT_NONACTIVE",     "dbo",   "MES_WIP_LOT_NONACTIVE",       f"WO = '{SAMPLE_WO}'"),
    ("MES_WIP_COMP",              "dbo",   "MES_WIP_COMP",                f"CURRENTLOT = '{SAMPLE_LOT}'"),
    ("MES_WIP_COMP_NONACTIVE",    "dbo",   "MES_WIP_COMP_NONACTIVE",      f"CURRENTLOT = '{SAMPLE_LOT}'"),
    ("MES_WIP_HIST",              "dbo",   "MES_WIP_HIST",                f"LOT = '{SAMPLE_LOT}'"),
    ("DM.AOI_WIP_COMP_OPERATION", "DM",    "AOI_WIP_COMP_OPERATION",      f"WO = '{SAMPLE_WO}'"),
    ("MES_WIP_REPAIR",            "dbo",   "MES_WIP_REPAIR",              "1=1"),
    ("MES_WIP_SCRAP",             "dbo",   "MES_WIP_SCRAP",               "CANCELFLAG = 'N'"),
    ("MES_EQP_EQP",               "dbo",   "MES_EQP_EQP",                 "1=1"),
    ("AOI_DEVICE_GROUP",          "dbo",   "AOI_DEVICE_GROUP",            "1=1"),
]

# Inferred FK relationships for reference section
RELATIONSHIPS = [
    ("MES_WPC_WO.WO",              "→", "DM.AOI_WIP_COMP_OPERATION.WO"),
    ("MES_WPC_WO.WO",              "→", "MES_WIP_LOT.WO"),
    ("MES_WPC_WO.WO",              "→", "MES_WIP_LOT_NONACTIVE.WO"),
    ("MES_WPC_WO.WO",              "→", "MES_WIP_SCRAP.WO  (assumed)"),
    ("MES_WPC_WO.WPC_WO_SID",     "→", "AOI_WO_RUNCARD.WPC_WO_SID"),
    ("MES_WIP_LOT.LOT",            "→", "MES_WIP_COMP.CURRENTLOT"),
    ("MES_WIP_LOT.LOT",            "→", "MES_WIP_COMP_NONACTIVE.CURRENTLOT"),
    ("MES_WIP_LOT.LOT",            "→", "MES_WIP_HIST.LOT"),
    ("MES_WIP_LOT.LOT",            "→", "MES_WIP_REPAIR.LOT"),
    ("DM.AOI_WIP_COMP_OPERATION.WIP_COMP_SID", "→", "MES_WIP_COMP.WIP_COMP_SID  (assumed)"),
    ("MES_EQP_EQP.SERIALNO",      "→", "US_SQL02.CHIPDATA.dbo.SPDEquipment.ID  (cross-server)"),
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_str(val) -> str:
    if val is None:
        return "NULL"
    if isinstance(val, (datetime, date, time)):
        return str(val)
    if isinstance(val, Decimal):
        return str(val)
    return str(val)


def _col_schema(conn, schema: str, table: str) -> list[dict]:
    """Fetch column metadata from INFORMATION_SCHEMA.COLUMNS."""
    sql = """
        SELECT ORDINAL_POSITION, COLUMN_NAME, DATA_TYPE,
               CHARACTER_MAXIMUM_LENGTH, NUMERIC_PRECISION, NUMERIC_SCALE,
               IS_NULLABLE
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
        ORDER BY ORDINAL_POSITION
    """
    try:
        rows = conn.cursor().execute(sql, schema, table).fetchall()
        result = []
        for r in rows:
            type_str = r.DATA_TYPE
            if r.CHARACTER_MAXIMUM_LENGTH:
                type_str += f"({r.CHARACTER_MAXIMUM_LENGTH})"
            elif r.NUMERIC_PRECISION is not None:
                type_str += f"({r.NUMERIC_PRECISION},{r.NUMERIC_SCALE})"
            result.append({
                "pos":      r.ORDINAL_POSITION,
                "name":     r.COLUMN_NAME,
                "type":     type_str,
                "nullable": r.IS_NULLABLE,
            })
        return result
    except Exception as e:
        return [{"pos": 0, "name": f"ERROR: {e}", "type": "", "nullable": ""}]


def _row_count(conn, full_table: str, where: str) -> int:
    try:
        sql = f"SELECT COUNT(*) FROM {full_table} WHERE {where}"
        return conn.cursor().execute(sql).fetchone()[0]
    except Exception:
        return -1


def _sample_rows(conn, full_table: str, where: str, order: str = "") -> tuple[list[str], list[list[str]]]:
    order_clause = f"ORDER BY {order}" if order else ""
    sql = f"SELECT TOP 5 * FROM {full_table} WHERE {where} {order_clause}"
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        cols = [d[0] for d in cursor.description]
        rows = [[_safe_str(v) for v in r] for r in cursor.fetchall()]
        return cols, rows
    except Exception as e:
        return [f"ERROR: {e}"], []


def _fmt_table(headers: list[str], rows: list[list[str]], max_col_w: int = 30) -> str:
    if not rows:
        return "  (no rows returned)\n"
    widths = [min(max_col_w, max(len(h), max((len(r[i]) for r in rows), default=0)))
              for i, h in enumerate(headers)]
    sep  = "  " + "-+-".join("-" * w for w in widths)
    hdr  = "  " + " | ".join(h[:widths[i]].ljust(widths[i]) for i, h in enumerate(headers))
    body = "\n".join(
        "  " + " | ".join(str(v)[:widths[i]].ljust(widths[i]) for i, v in enumerate(row))
        for row in rows
    )
    return f"{hdr}\n{sep}\n{body}\n"


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    out_dir   = os.path.dirname(os.path.abspath(__file__))
    txt_path  = os.path.join(out_dir, "schema_log.txt")
    json_path = os.path.join(out_dir, "schema_columns.json")

    print(f"Connecting to {CONN_STR.split('SERVER=')[1].split(';')[0]} …")
    try:
        conn = pyodbc.connect(CONN_STR, timeout=15)
        print("  Connected OK\n")
    except Exception as e:
        print(f"  FAILED: {e}")
        return

    lines  = []
    schema_json = {}

    def w(s=""):
        lines.append(s)
        print(s)

    w(f"MES Schema Exploration — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    w(f"Server : US_SQL01.USPL.HOME  Database: MES")
    w(f"Sample WO  : {SAMPLE_WO}")
    w(f"Sample LOT : {SAMPLE_LOT}")
    w("=" * 90)

    order_hints = {
        "MES_WIP_HIST": "SEQUENCE",
        "DM.AOI_WIP_COMP_OPERATION": "STARTSEQ",
    }

    for (display, sql_schema, sql_table, where) in TABLES:
        full_table = f"{sql_schema}.{sql_table}" if sql_schema and sql_schema != "dbo" else sql_table
        w()
        w("=" * 90)
        w(f"  TABLE : {display}")
        w("=" * 90)

        # Row count
        cnt = _row_count(conn, full_table, where)
        w(f"  Row count (filtered): {cnt:,}" if cnt >= 0 else "  Row count: ERROR")

        # Column schema
        if sql_schema:
            cols_meta = _col_schema(conn, sql_schema, sql_table)
            w()
            w("  COLUMNS (from INFORMATION_SCHEMA):")
            w(f"  {'#':>3}  {'Column Name':<35}  {'SQL Type':<25}  Nullable")
            w(f"  {'---':>3}  {'-'*35}  {'-'*25}  --------")
            for c in cols_meta:
                w(f"  {c['pos']:>3}  {c['name']:<35}  {c['type']:<25}  {c['nullable']}")
            schema_json[display] = cols_meta
        else:
            w("  (view — column list from runtime description below)")

        # Sample data
        order = order_hints.get(display, "")
        col_names, sample = _sample_rows(conn, full_table, where, order)
        w()
        w(f"  SAMPLE DATA (up to 5 rows, WHERE {where}):")
        w(_fmt_table(col_names, sample))

        # If view, capture columns from runtime description
        if not sql_schema and col_names and "ERROR" not in col_names[0]:
            schema_json[display] = [{"name": c} for c in col_names]

    # Relationships
    w()
    w("=" * 90)
    w("  INFERRED TABLE RELATIONSHIPS")
    w("=" * 90)
    for src, arrow, dst in RELATIONSHIPS:
        w(f"  {src:<50} {arrow}  {dst}")

    conn.close()

    # Write files
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n  Saved: {txt_path}")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(schema_json, f, indent=2)
    print(f"  Saved: {json_path}")


if __name__ == "__main__":
    main()
