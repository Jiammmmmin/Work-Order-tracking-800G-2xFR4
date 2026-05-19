"""
MES connectivity diagnostic — run from project root (same folder as main.py):

    python mes_connection_diagnose.py
    python mes_connection_diagnose.py --days 7 --timeout 300 --product COS

Step 6 can be slow (large MES joins). Default is --days 1 and --timeout 120.

Determines whether failures are likely:
  - local / backend environment (Python, pyodbc, ODBC driver)
  - network or SQL Server host down / blocked
  - authentication / database access
  - application SQL vs MES schema/permissions (connection OK but query fails)
"""

from __future__ import annotations

import argparse
import re
import socket
import sys
import threading
from datetime import date, timedelta
from pathlib import Path

# Ensure `import app.backend.mes` works when launched as a script
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _print(title: str, body: str = "") -> None:
    line = "=" * 60
    print(f"\n{line}\n{title}\n{line}", flush=True)
    if body:
        print(body.rstrip(), flush=True)


def _say(msg: str) -> None:
    print(msg, flush=True)


def _server_host_from_conn_str(conn_str: str) -> str | None:
    m = re.search(r"SERVER=([^;]+)", conn_str, re.I)
    return m.group(1).strip() if m else None


def step_import_pyodbc() -> tuple[bool, str]:
    try:
        import pyodbc  # noqa: F401

        return True, "pyodbc import OK."
    except Exception as e:
        return False, f"pyodbc import failed: {type(e).__name__}: {e}\n→ Fix: pip install pyodbc (local environment / backend dependency)."


def step_list_odbc_drivers() -> tuple[bool, str]:
    try:
        import pyodbc

        drivers = list(pyodbc.drivers())
        if not drivers:
            return False, "No ODBC drivers registered.\n→ Fix: install an ODBC driver for SQL Server on this machine."
        lines = ["Installed ODBC drivers (subset shown if many):"]
        for d in sorted(drivers):
            lines.append(f"  - {d}")
        body = "\n".join(lines)
        # mes.py uses DRIVER=SQL Server (legacy ODBC)
        legacy = any("SQL Server" == d or d.endswith("\\SQL Server") for d in drivers)
        if not legacy:
            body += (
                "\n\n⚠ mes.py uses DRIVER=SQL Server; that legacy driver is not listed."
                "\n→ Either install 'SQL Server' ODBC driver, or change CONN_STR in mes.py"
                " to e.g. ODBC Driver 17 for SQL Server."
            )
            return False, body
        return True, body
    except Exception as e:
        return False, f"Could not enumerate ODBC drivers: {e}"


def step_tcp_sql_port(host: str, port: int = 1433, timeout: float = 5.0) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
        return True, f"TCP connect to {host}:{port} succeeded (host reachable, port open)."
    except socket.gaierror as e:
        return False, f"DNS / hostname resolution failed for {host!r}: {e}\n→ Check VPN, DNS, or hostname spelling."
    except (TimeoutError, OSError) as e:
        return False, (
            f"TCP connect to {host}:{port} failed: {type(e).__name__}: {e}\n"
            "→ Likely: SQL Server down, wrong port, corporate firewall, or not on required network/VPN.\n"
            "→ This points to infrastructure / MES host availability, not Python app logic."
        )


def step_pyodbc_connect(conn_str: str) -> tuple[bool, str, object | None]:
    import pyodbc

    try:
        conn = pyodbc.connect(conn_str, timeout=15)
        return True, "pyodbc.connect() succeeded.", conn
    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        hint = ""
        low = str(e).lower()
        if "login failed" in low or "28000" in low:
            hint = "\n→ SQL Server is likely reachable; credentials or login permission issue (not 'host completely down')."
        elif "timeout" in low or "timed out" in low or "10060" in low:
            hint = "\n→ Typical: server not accepting connections, firewall, or need VPN (MES/SQL path)."
        elif "named pipes" in low or "provider" in low or "08001" in low:
            hint = "\n→ Network / SQL Server endpoint / driver mismatch."
        return False, msg + hint, None


def step_simple_query(conn) -> tuple[bool, str]:
    cur = None
    try:
        cur = conn.cursor()
        cur.execute("SELECT GETDATE() AS server_time")
        row = cur.fetchone()
        t = row[0] if row else None
        return True, f"SELECT GETDATE() OK. Server time: {t!r}"
    except Exception as e:
        return False, f"Simple query failed: {type(e).__name__}: {e}"
    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass


def step_by_date_query(
    conn,
    sql_by_date: str,
    mes_type: str,
    device_group: str,
    *,
    span_days: int,
    query_timeout_sec: int,
) -> tuple[bool, str]:
    import pyodbc

    end = date.today()
    span = max(1, span_days)
    start = end - timedelta(days=span - 1)
    start_s = start.strftime("%Y/%m/%d")
    end_s = end.strftime("%Y/%m/%d")
    cur = None
    try:
        cur = conn.cursor()
        # Query timeout: only some pyodbc builds expose Cursor.timeout (older wheels raise AttributeError).
        timeout_applied: int | None = None
        if hasattr(cur, "timeout"):
            cur.timeout = query_timeout_sec
            timeout_applied = query_timeout_sec
        cur.execute(sql_by_date, start_s, end_s, mes_type, device_group)
        rows = cur.fetchall()
        tnote = (
            f"statement_timeout={timeout_applied}s (ODBC)."
            if timeout_applied is not None
            else (
                "statement_timeout=not set (this pyodbc has no Cursor.timeout; "
                "upgrade pyodbc or wait on heavy queries; --timeout is ignored for ODBC)."
            )
        )
        return True, (
            f"_SQL_BY_DATE OK ({len(rows)} row(s); window {start_s} .. {end_s}, "
            f"DEVICETYPE={mes_type!r}, DEVICEGROUP={device_group!r}; {tnote})\n"
            "If the UI still fails, compare product_type / date range / worker thread vs this script."
        )
    except pyodbc.OperationalError as e:
        err = str(e).lower()
        if "timeout" in err or "timed out" in err:
            return False, (
                f"Date-range WO query timed out after {query_timeout_sec}s: {e}\n"
                "→ MES/SQL is reachable; this statement is heavy or blocked (locks), not a dead host.\n"
                "→ Try a narrower window: python mes_connection_diagnose.py --days 1 --timeout 300"
            )
        return False, (
            f"Date-range WO query failed: OperationalError: {e}\n"
            "→ Connection path works; failure is SQL Server execution (permissions, locks, bad plan)."
        )
    except Exception as e:
        return False, (
            f"Date-range WO query failed: {type(e).__name__}: {e}\n"
            "→ Connection and auth work; failure is at SQL level (permissions, missing tables/views, "
            "or query mismatch with MES schema). This is not 'MES TCP completely down'."
        )
    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass


def main() -> int:
    p = argparse.ArgumentParser(description="MES / pyodbc connectivity and _SQL_BY_DATE check.")
    p.add_argument(
        "--days",
        type=int,
        default=1,
        metavar="N",
        help="Date span for Step 6 (ENDSHIFT BETWEEN start..end). Default 1 = today only (faster). Use 7 to match old script.",
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=120,
        metavar="SEC",
        help="ODBC query timeout for Step 6 only (seconds). Default 120.",
    )
    p.add_argument(
        "--product",
        default="COS",
        choices=["COS", "BOSA", "TTX"],
        help="UI product_type for _TYPE_MAP / _DEVICE_GROUP_MAP (default COS).",
    )
    args = p.parse_args()

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(line_buffering=True)
        except Exception:
            pass

    _print("MES connection diagnostic", "Steps are ordered: environment → network → SQL → app SQL.")

    ok, msg = step_import_pyodbc()
    _print("Step 1 — import pyodbc", msg)
    if not ok:
        return 1

    ok, msg = step_list_odbc_drivers()
    _print("Step 2 — ODBC drivers (must include legacy 'SQL Server' for current mes.py)", msg)
    if not ok:
        return 1

    try:
        from app.backend.mes import CONN_STR, _DEVICE_GROUP_MAP, _SQL_BY_DATE, _TYPE_MAP
    except Exception as e:
        _print(
            "Step 3 — import app.backend.mes",
            f"Failed to import mes module: {type(e).__name__}: {e}\n"
            "→ Run this script from the project folder that contains main.py and the app/ package.",
        )
        return 1

    host = _server_host_from_conn_str(CONN_STR)
    if not host:
        _print("Step 3b — parse SERVER from CONN_STR", "Could not parse SERVER= from CONN_STR.")
        return 1

    ok, msg = step_tcp_sql_port(host)
    _print(f"Step 3 — TCP to {host}:1433 (default SQL Server port)", msg)
    if not ok:
        _print(
            "Interpretation",
            "TCP failed before ODBC. Most likely: network/VPN/firewall or SQL Server not listening on 1433.\n"
            "This is usually not a bug in _by_date() Python code.",
        )
        # Still try ODBC in case port is non-default / TCP test false negative
        _say("\n(Continuing with ODBC anyway — some setups use non-1433 or dynamic ports.)")

    ok, msg, conn = step_pyodbc_connect(CONN_STR)
    _print("Step 4 — pyodbc.connect (same CONN_STR as mes.py)", msg)
    if not ok or conn is None:
        _print(
            "Summary",
            "ODBC connection failed. If Step 3 TCP also failed → treat as MES/SQL host or network path.\n"
            "If TCP OK but ODBC fails → SQL auth, database name, encryption/SSL, or driver details.",
        )
        return 1

    try:
        ok, msg = step_simple_query(conn)
        _print("Step 5 — SELECT GETDATE()", msg)
        if not ok:
            return 1
    finally:
        try:
            conn.close()
        except Exception:
            pass

    # Fresh connection for Step 6: some ODBC/SQL Server combinations stall if the next
    # heavy statement reuses the same connection right after a lightweight probe.
    _say(
        ">>> Step 5 connection closed. Opening a NEW connection for Step 6 "
        f"(product={args.product!r}, days={args.days}, timeout={args.timeout}s)..."
    )

    product = args.product
    mes_type = _TYPE_MAP.get(product, product)
    device_group = _DEVICE_GROUP_MAP.get(product, "")

    ok, msg, conn6 = step_pyodbc_connect(CONN_STR)
    if not ok or conn6 is None:
        _print(
            "Step 6 — pyodbc.connect (second connection)",
            msg or "Second pyodbc.connect() returned no connection.",
        )
        return 1
    _print("Step 6 — pyodbc.connect (second connection)", "OK (dedicated connection for _SQL_BY_DATE).")

    stop_hb = threading.Event()

    def _heartbeat() -> None:
        n = 0
        while not stop_hb.wait(10):
            n += 1
            _say(f"  ... Step 6: SQL still executing (>= {n * 10}s wall time; ODBC timeout={args.timeout}s)")

    hb = threading.Thread(target=_heartbeat, daemon=True)
    hb.start()
    try:
        _print(
            f"Step 6 — full _SQL_BY_DATE (product_type={product!r} → MES mapping)",
            (
                "Running heavy query; heartbeat prints every 10s while waiting.\n"
                f"span_days={args.days}, query_timeout={args.timeout}s."
            ),
        )
        ok, msg = step_by_date_query(
            conn6,
            _SQL_BY_DATE,
            mes_type,
            device_group,
            span_days=args.days,
            query_timeout_sec=args.timeout,
        )
    finally:
        stop_hb.set()

    try:
        conn6.close()
    except Exception:
        pass

    _print("Step 6 — result", msg)
    if not ok:
        _print(
            "Summary",
            "Server is up and credentials work for simple queries, but the WO-by-date query failed.\n"
            "Isolate: MES object permissions, renamed views, or SQL text — not generic 'MES down'.",
        )
        return 1

    _print(
        "Summary — all steps passed",
        "From this machine: MES SQL responds, auth works, and the same _SQL_BY_DATE used by _by_date() runs.\n"
        "If the desktop app still errors, check UI thread, QueryParams (dates/product), or errors swallowed elsewhere.",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
