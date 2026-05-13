"""
MES SQL Server client — US_SQL01.USPL.HOME / MES

Yield source: v_MasterWOInfo.SCRAPQTY / WOQTY
Operation history: DM.AOI_WIP_COMP_OPERATION JOIN MES_WIP_COMP ON WIP_COMP_SID
Lot tracking: MES_WIP_LOT + MES_WIP_LOT_NONACTIVE + MES_WIP_HIST (CheckIn / EndOfOperation)
"""

import pyodbc
from datetime import date, datetime
from typing import List, Tuple

from .data_models import WorkOrderData, LotData, LotOperationData, OperationData, FailCodeData, QueryParams, QueryResult

# ── Connection ────────────────────────────────────────────────────────────────

CONN_STR = (
    r"DRIVER=SQL Server;"
    r"SERVER=US_SQL01.USPL.HOME;"
    r"DATABASE=MES;"
    r"UID=LABVIEW;"
    r"PWD=LABVIEW;"
)

# UI label  →  MES DEVICETYPE value
_TYPE_MAP = {"BOSA": "BOS", "COS": "COS", "TTX": "TTX"}

# UI label  →  AOI_DEVICE_GROUP.DEVICEGROUP value
_DEVICE_GROUP_MAP = {
    "COS":  "800G_2xFR4_AW_COS",
    "BOSA": "800G_2xFR4_AW_BOS",
    "TTX":  "800G_2xFR4_AW_TRX",
}


def _connect() -> pyodbc.Connection:
    return pyodbc.connect(CONN_STR, timeout=15)


def _parse_date(val) -> date:
    """Handle nvarchar '2026/04/25', actual date, or datetime."""
    if val is None:
        return date.today()
    if isinstance(val, (date, datetime)):
        return val if isinstance(val, date) else val.date()
    s = str(val).strip()
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return date.today()


# ── SQL ───────────────────────────────────────────────────────────────────────

_SQL_BY_DATE = """
    SELECT DISTINCT
        W.DEVICETYPE,
        W.WO,
        W.MAKTX,
        W.SCHEDULEDATE,
        V.WOSTATUS,
        V.FINISHED,
        V.STARTDATE,
        CAST(V.WOQTY    AS INT) AS WOQTY,
        CAST(V.WIPQTY   AS INT) AS WIPQTY,
        CAST(V.REPAIRQTY AS INT) AS REPAIRQTY,
        CAST(V.SCRAPQTY  AS INT) AS SCRAPQTY,
        CAST(V.INVQTY    AS INT) AS INVQTY,
        CASE WHEN V.WOQTY > 0
             THEN CAST(V.WOQTY - V.SCRAPQTY - V.REPAIRQTY AS FLOAT) / CAST(V.WOQTY AS FLOAT) * 100
             ELSE 0 END          AS YIELD_PCT
    FROM  DM.AOI_WIP_COMP_OPERATION O
    INNER JOIN MES_WPC_WO       W  ON W.WO     = O.WO
    INNER JOIN v_MasterWOInfo   V  ON V.WO     = O.WO
    INNER JOIN AOI_DEVICE_GROUP DG ON DG.DEVICE = W.DEVICE
    WHERE O.ENDSHIFT BETWEEN ? AND ?
      AND W.DEVICETYPE    = ?
      AND DG.DEVICEGROUP  = ?
    ORDER BY W.WO
"""

_SQL_BY_WO_LIST = """
    SELECT DISTINCT
        W.DEVICETYPE,
        W.WO,
        W.MAKTX,
        W.SCHEDULEDATE,
        V.WOSTATUS,
        V.FINISHED,
        V.STARTDATE,
        CAST(V.WOQTY    AS INT) AS WOQTY,
        CAST(V.WIPQTY   AS INT) AS WIPQTY,
        CAST(V.REPAIRQTY AS INT) AS REPAIRQTY,
        CAST(V.SCRAPQTY  AS INT) AS SCRAPQTY,
        CAST(V.INVQTY    AS INT) AS INVQTY,
        CASE WHEN V.WOQTY > 0
             THEN CAST(V.WOQTY - V.SCRAPQTY - V.REPAIRQTY AS FLOAT) / CAST(V.WOQTY AS FLOAT) * 100
             ELSE 0 END          AS YIELD_PCT
    FROM  MES_WPC_WO       W
    INNER JOIN v_MasterWOInfo   V  ON V.WO      = W.WO
    INNER JOIN AOI_DEVICE_GROUP DG ON DG.DEVICE = W.DEVICE
    WHERE W.WO IN ({ph})
      AND W.DEVICETYPE   = ?
      AND DG.DEVICEGROUP = ?
    ORDER BY W.WO
"""

# Per-WO per-operation history aggregated from DM.AOI_WIP_COMP_OPERATION.
# Joined with MES_WIP_COMP on WIP_COMP_SID to scope to trackable components.
# MIN(STARTSEQ) drives the column order (matches the physical route sequence).
_SQL_OPERATION_HISTORY = """
    SELECT
        O.WO,
        O.OPERATION,
        MIN(O.STARTSEQ)                                        AS OP_SEQ,
        COUNT(DISTINCT O.WIP_COMP_SID)                        AS UNIT_COUNT,
        SUM(CASE WHEN O.SCRAP_FLAG  = 'Y' THEN 1 ELSE 0 END) AS SCRAP_COUNT,
        SUM(CASE WHEN O.REPAIR_FLAG = 'Y' THEN 1 ELSE 0 END) AS REPAIR_COUNT,
        MIN(O.BEGINTIME)                                      AS START_TIME,
        MAX(O.ENDTIME)                                        AS END_TIME,
        MAX(O.EQUIPMENT)                                      AS EQUIPMENT
    FROM DM.AOI_WIP_COMP_OPERATION O
    INNER JOIN MES_WIP_COMP C ON C.WIP_COMP_SID = O.WIP_COMP_SID
    WHERE O.WO IN ({ph})
    GROUP BY O.WO, O.OPERATION
    ORDER BY O.WO, MIN(O.STARTSEQ)
"""

_SQL_ALL_LOTS = """
    SELECT LOT, WO, ISNULL(PICKUPNO, LOT) AS PICKUPNO,
           CAST(QUANTITY AS INT)           AS QUANTITY,
           STATUS, OPERATION,
           ISNULL(BAR,   '') AS BAR,
           ISNULL(UTRAY, '') AS UTRAY
    FROM   MES_WIP_LOT
    WHERE  WO IN ({ph})
    UNION ALL
    SELECT LOT, WO, ISNULL(PICKUPNO, LOT) AS PICKUPNO,
           CAST(QUANTITY AS INT)           AS QUANTITY,
           STATUS, OPERATION,
           ISNULL(BAR,   '') AS BAR,
           ISNULL(UTRAY, '') AS UTRAY
    FROM   MES_WIP_LOT_NONACTIVE
    WHERE  WO IN ({ph})
    ORDER BY WO, LOT
"""

_SQL_LOT_OPERATIONS = """
    SELECT
        O.LOT,
        O.OPERATION,
        MIN(O.STARTSEQ)                                        AS OP_SEQ,
        COUNT(DISTINCT O.WIP_COMP_SID)                        AS UNIT_COUNT,
        SUM(CASE WHEN O.SCRAP_FLAG  = 'Y' THEN 1 ELSE 0 END) AS SCRAP_COUNT,
        SUM(CASE WHEN O.REPAIR_FLAG = 'Y' THEN 1 ELSE 0 END) AS REPAIR_COUNT,
        MIN(O.BEGINTIME)                                      AS START_TIME,
        MAX(O.ENDTIME)                                        AS END_TIME,
        MAX(O.EQUIPMENT)                                      AS EQUIPMENT
    FROM DM.AOI_WIP_COMP_OPERATION O
    WHERE O.WO IN ({ph})
    GROUP BY O.LOT, O.OPERATION
    ORDER BY O.LOT, MIN(O.STARTSEQ)
"""

# Fail codes — scraps from AOI_WIP_COMP_OPERATION (SCRAP_REASON),
#              repairs from MES_WIP_REPAIR (DEFECT_REASON).
# Both joined to MES_WIP_REASON (REASON = code, DESCR = description).
# Parameters: wo_numbers passed TWICE — once per UNION branch.
_SQL_FAIL_CODES = """
    SELECT OPERATION, FAIL_CODE, FAIL_DESC, SUM(CNT) AS CNT
    FROM (
        SELECT
            O.OPERATION,
            ISNULL(NULLIF(LTRIM(RTRIM(O.SCRAP_REASON)), ''), 'UNKNOWN') AS FAIL_CODE,
            ISNULL(NULLIF(LTRIM(RTRIM(RW.DESCR)),        ''), '')        AS FAIL_DESC,
            COUNT(*)                                                      AS CNT
        FROM DM.AOI_WIP_COMP_OPERATION O
        LEFT JOIN MES_WIP_REASON RW
               ON LTRIM(RTRIM(RW.REASON)) = LTRIM(RTRIM(O.SCRAP_REASON))
        WHERE O.WO IN ({ph})
          AND O.SCRAP_FLAG = 'Y'
        GROUP BY O.OPERATION, O.SCRAP_REASON, RW.DESCR

        UNION ALL

        SELECT
            REP.OPERATION,
            ISNULL(NULLIF(LTRIM(RTRIM(REP.DEFECT_REASON)), ''), 'UNKNOWN') AS FAIL_CODE,
            ISNULL(NULLIF(LTRIM(RTRIM(RW2.DESCR)),          ''), '')        AS FAIL_DESC,
            COUNT(*)                                                         AS CNT
        FROM MES_WIP_REPAIR REP
        LEFT JOIN MES_WIP_REASON RW2
               ON LTRIM(RTRIM(RW2.REASON)) = LTRIM(RTRIM(REP.DEFECT_REASON))
        WHERE REP.WO IN ({ph})
          AND REP.CANCELFLAG = 'N'
        GROUP BY REP.OPERATION, REP.DEFECT_REASON, RW2.DESCR
    ) combined
    GROUP BY OPERATION, FAIL_CODE, FAIL_DESC
    ORDER BY OPERATION, SUM(CNT) DESC
"""

_SQL_PING = "SELECT GETDATE()"


# ── MesDatabase ───────────────────────────────────────────────────────────────

class MesDatabase:
    """Live MES SQL Server backend."""

    def ping(self) -> bool:
        try:
            with _connect() as conn:
                conn.cursor().execute(_SQL_PING)
            return True
        except Exception:
            return False

    def query_summary(self, params: QueryParams) -> QueryResult:
        if params.query_type == "Date":
            wos = self._by_date(params)
        else:
            wos = self._by_wo_list(params)

        if not wos:
            return QueryResult(query_params=params)

        wo_nums              = [w.wo_number for w in wos]
        op_hist              = self.get_operation_history(wo_nums)
        lot_tracking, lot_ops = self.get_lot_tracking(wo_nums)
        fail_codes = self.get_fail_codes(wo_nums)
        yields    = [w.yield_pct for w in wos]
        total_qty = sum(w.total_qty for w in wos)
        total_inv = sum(w.inv_qty   for w in wos)
        avg_yield = round(sum(yields) / len(yields), 2)
        return QueryResult(
            work_orders=wos,
            operation_history=op_hist,
            lot_tracking=lot_tracking,
            lot_operations=lot_ops,
            avg_yield=avg_yield,
            min_yield=round(min(yields), 2),
            max_yield=round(max(yields), 2),
            total_wos=len(wos),
            total_planned_qty=total_qty,
            total_pass_qty=total_inv,
            total_scrap_qty=sum(w.scrap_qty   for w in wos),
            total_wip_qty=sum(w.wip_qty       for w in wos),
            total_inv_qty=total_inv,
            total_repair_qty=sum(w.repair_qty for w in wos),
            fail_codes=fail_codes,
            query_params=params,
        )

    def get_operation_history(self, wo_numbers: List[str]) -> List[OperationData]:
        if not wo_numbers:
            return []
        ph  = ",".join("?" * len(wo_numbers))
        sql = _SQL_OPERATION_HISTORY.format(ph=ph)
        with _connect() as conn:
            rows = conn.cursor().execute(sql, *wo_numbers).fetchall()
        return [
            OperationData(
                wo=r.WO,
                operation=r.OPERATION or "",
                op_seq=int(r.OP_SEQ or 0),
                unit_count=int(r.UNIT_COUNT or 0),
                scrap_count=int(r.SCRAP_COUNT or 0),
                repair_count=int(r.REPAIR_COUNT or 0),
                start_time=r.START_TIME,
                end_time=r.END_TIME,
                equipment=r.EQUIPMENT or "",
            )
            for r in rows
        ]

    def get_lot_tracking(
        self, wo_numbers: List[str]
    ) -> Tuple[List[LotData], List[LotOperationData]]:
        """Return (lots, lot_operations) for the given WO numbers.

        Lots come from MES_WIP_LOT UNION MES_WIP_LOT_NONACTIVE.
        Lot operations come from DM.AOI_WIP_COMP_OPERATION joined with
        MES_WIP_COMP + MES_WIP_COMP_NONACTIVE — gives proper BEGINTIME/ENDTIME
        datetimes plus scrap/repair counts per lot per operation.
        """
        if not wo_numbers:
            return [], []

        ph = ",".join("?" * len(wo_numbers))

        # ── Lots (active + finished) ───────────────────────────────────────
        with _connect() as conn:
            lot_rows = conn.cursor().execute(
                _SQL_ALL_LOTS.format(ph=ph), *wo_numbers, *wo_numbers
            ).fetchall()

        lots = [
            LotData(
                lot=r.LOT,
                wo=r.WO,
                pickupno=r.PICKUPNO or r.LOT,
                quantity=int(r.QUANTITY or 0),
                status=r.STATUS or "",
                operation=r.OPERATION or "",
                bar=r.BAR or "",
                utray=r.UTRAY or "",
            )
            for r in lot_rows
        ]

        # ── Per-lot per-operation from DM.AOI_WIP_COMP_OPERATION ──────────
        # LOT column exists directly on the table — no MES_WIP_COMP join needed.
        with _connect() as conn:
            op_rows = conn.cursor().execute(
                _SQL_LOT_OPERATIONS.format(ph=ph), *wo_numbers
            ).fetchall()

        lot_ops = [
            LotOperationData(
                lot=r.LOT,
                operation=r.OPERATION or "",
                op_seq=float(r.OP_SEQ or 0),
                unit_count=int(r.UNIT_COUNT or 0),
                scrap_count=int(r.SCRAP_COUNT or 0),
                repair_count=int(r.REPAIR_COUNT or 0),
                start_time=r.START_TIME,
                end_time=r.END_TIME,
                equipment=r.EQUIPMENT or "",
            )
            for r in op_rows
            if r.LOT is not None   # skip WO-level rows with no lot assignment
        ]
        return lots, lot_ops

    def get_fail_codes(self, wo_numbers: List[str]) -> List[FailCodeData]:
        """Fail-code counts: scraps from AOI_WIP_COMP_OPERATION, repairs from MES_WIP_REPAIR.
        Both joined to MES_WIP_REASON for human-readable descriptions.
        wo_numbers is passed twice — once per UNION branch.
        """
        if not wo_numbers:
            return []
        ph  = ",".join("?" * len(wo_numbers))
        sql = _SQL_FAIL_CODES.format(ph=ph)
        params = list(wo_numbers) + list(wo_numbers)   # two placeholders in UNION
        try:
            with _connect() as conn:
                rows = conn.cursor().execute(sql, *params).fetchall()
        except Exception:
            return []
        return [
            FailCodeData(
                operation=r.OPERATION or "",
                fail_code=r.FAIL_CODE  or "UNKNOWN",
                fail_desc=r.FAIL_DESC  or "",
                count=int(r.CNT or 0),
            )
            for r in rows
            if (r.CNT or 0) > 0
        ]

    # ── private ───────────────────────────────────────────────────────────────

    def _by_date(self, params: QueryParams) -> List[WorkOrderData]:
        mes_type     = _TYPE_MAP.get(params.product_type, params.product_type)
        device_group = _DEVICE_GROUP_MAP.get(params.product_type, "")
        start = params.start_date.strftime("%Y/%m/%d")
        end   = params.end_date.strftime("%Y/%m/%d")
        with _connect() as conn:
            rows = conn.cursor().execute(
                _SQL_BY_DATE, start, end, mes_type, device_group
            ).fetchall()
        return [_row_to_wo(r, params.product_type) for r in rows]

    def _by_wo_list(self, params: QueryParams) -> List[WorkOrderData]:
        if not params.wo_list:
            return []
        mes_type     = _TYPE_MAP.get(params.product_type, params.product_type)
        device_group = _DEVICE_GROUP_MAP.get(params.product_type, "")
        ph  = ",".join("?" * len(params.wo_list))
        sql = _SQL_BY_WO_LIST.format(ph=ph)
        with _connect() as conn:
            rows = conn.cursor().execute(
                sql, *params.wo_list, mes_type, device_group
            ).fetchall()
        return [_row_to_wo(r, params.product_type) for r in rows]


# ── row mapper ────────────────────────────────────────────────────────────────

def _row_to_wo(row, ui_product_type: str) -> WorkOrderData:
    total_qty  = int(row.WOQTY     or 0)
    scrap_qty  = int(row.SCRAPQTY  or 0)
    repair_qty = int(row.REPAIRQTY or 0)
    wip_qty    = int(row.WIPQTY    or 0)
    inv_qty    = int(row.INVQTY    or 0)
    finished   = row.FINISHED or "N"
    status     = row.WOSTATUS or ""

    pass_qty = inv_qty

    if inv_qty > 0:
        yield_pct = round(inv_qty / total_qty * 100, 2) if total_qty else 0.0
    else:
        denom = wip_qty + repair_qty + scrap_qty
        yield_pct = round(wip_qty / denom * 100, 2) if denom else 0.0

    return WorkOrderData(
        wo_number=row.WO,
        product_type=ui_product_type,
        yield_pct=yield_pct,
        start_date=_parse_date(row.STARTDATE),
        end_date=_parse_date(row.SCHEDULEDATE),
        status=status,
        station="",
        total_qty=total_qty,
        pass_qty=pass_qty,
        planned_qty=total_qty,
        schedule_date=_parse_date(row.SCHEDULEDATE),
        maktx=row.MAKTX or "",
        wip_qty=wip_qty,
        inv_qty=inv_qty,
        repair_qty=repair_qty,
        scrap_qty=scrap_qty,
        finished=finished,
    )
