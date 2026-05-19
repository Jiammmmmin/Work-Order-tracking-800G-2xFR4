#!/usr/bin/env python3
"""
MES connectivity smoke test (same connection string + ping + date-range WO query as the app).

Run from repo root:
  python scripts/test_mes_connection.py
  python scripts/test_mes_connection.py --product COS --start 2026-04-01 --end 2026-04-30

Exit codes: 0 = ping OK and query ran (may return 0 rows); 1 = failure.
"""

from __future__ import annotations

import argparse
import sys
import traceback
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _exit_pyodbc_load_failed(exc: BaseException) -> None:
    """pyodbc fails at import if unixODBC is missing — not an MES server problem."""
    text = str(exc)
    print(
        "Cannot load pyodbc — this is a local ODBC runtime issue on your Mac,\n"
        "not proof that MES is down. (The UI falls back to demo data for the same reason.)\n"
        "\n"
        "本地无法加载 pyodbc（缺 ODBC 库），与 MES 是否在线无关；修好 ODBC 后才能测连接。\n"
    )
    if "libodbc" in text or "unixodbc" in text.lower():
        print(
            "Missing unixODBC (libodbc). Typical fix on Apple Silicon / Homebrew:\n"
            "  brew install unixodbc\n"
            "Then restart the terminal and run this script again.\n"
            "\n"
            "若仍报错，再安装 SQL Server 的 ODBC 驱动（与 mes.py 里 DRIVER= 名称一致），例如:\n"
            "  brew tap microsoft/mssql-release https://github.com/Microsoft/homebrew-mssql-release\n"
            "  brew install msodbcsql18\n"
            "并把 app/backend/mes.py 的 CONN_STR 改成 DRIVER={ODBC Driver 18 for SQL Server}; …\n"
        )
    print("--- Python error (for support) ---")
    print(text)
    raise SystemExit(2)


try:
    import pyodbc  # noqa: F401 — must succeed before app.backend.mes (mes imports pyodbc at import time)
except ImportError as exc:
    _exit_pyodbc_load_failed(exc)

from app.backend.data_models import QueryParams  # noqa: E402
from app.backend.mes import CONN_STR, MesDatabase, _connect  # noqa: E402


def _parse_date(s: str) -> date:
    y, m, d = s.strip().split("-")
    return date(int(y), int(m), int(d))


def main() -> int:
    p = argparse.ArgumentParser(description="Test MES pyodbc ping + _by_date query.")
    p.add_argument(
        "--product",
        default="COS",
        choices=("COS", "BOSA", "TTX"),
        help="UI product type (maps to MES DEVICETYPE + AOI_DEVICE_GROUP).",
    )
    p.add_argument(
        "--start",
        type=str,
        default=None,
        help="Start date YYYY-MM-DD (default: 30 days before --end).",
    )
    p.add_argument(
        "--end",
        type=str,
        default=None,
        help="End date YYYY-MM-DD (default: today).",
    )
    args = p.parse_args()

    end = _parse_date(args.end) if args.end else date.today()
    start = _parse_date(args.start) if args.start else (end - timedelta(days=30))

    print("--- ODBC drivers (pyodbc) ---")
    try:
        for d in pyodbc.drivers():
            print(f"  {d}")
    except Exception as exc:
        print(f"  (could not list drivers: {exc})")

    print("\n--- Connection string (password redacted) ---")
    redacted = CONN_STR.replace("PWD=LABVIEW;", "PWD=***;")
    print(f"  {redacted}")

    print("\n--- 1) Ping (SELECT GETDATE()) — same as UI MesDatabase.ping() ---")
    db = MesDatabase()
    try:
        ok = db.ping()
    except Exception:
        print("  MesDatabase.ping() raised:")
        traceback.print_exc()
        return 1
    if not ok:
        print("  Ping returned False (connection failed; exception was swallowed inside ping).")
        print("  Retrying with explicit connect + error text:")
        try:
            with _connect() as conn:
                cur = conn.cursor()
                cur.execute("SELECT GETDATE() AS server_time")
                row = cur.fetchone()
                print(f"  OK: {row}")
        except Exception:
            traceback.print_exc()
            return 1
    else:
        print("  OK — MES reachable for ping.")

    print("\n--- 2) Date-range WO list — MesDatabase._by_date() ---")
    params = QueryParams(
        product_type=args.product,
        query_type="Date",
        start_date=start,
        end_date=end,
    )
    print(f"  product={args.product!r}  start={start}  end={end}")
    try:
        wos = db._by_date(params)
    except Exception:
        print("  _by_date raised:")
        traceback.print_exc()
        return 1

    print(f"  Row count: {len(wos)}")
    for i, w in enumerate(wos[:15]):
        print(f"    {i + 1}. WO={w.wo_number!r}  yield%={w.yield_pct}  status={w.status!r}")
    if len(wos) > 15:
        print(f"    ... and {len(wos) - 15} more")

    if not wos:
        print(
            "\n  Note: 0 rows can mean OK SQL + empty window, or filters mismatch "
            "(DEVICETYPE / DEVICEGROUP / ENDSHIFT date format vs DB)."
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
