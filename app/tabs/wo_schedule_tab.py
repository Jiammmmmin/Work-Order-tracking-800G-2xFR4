"""
WO Schedule tab.

Top — Summary table (self.summary_table):
  Row 0 : TOTALS  — all WOs | all splits | overall date range | per-process yield | avg yield
  Rows 1+: per WO — wo# (splits) | start | end | per-process yield | overall yield

Bottom — Matrix table (self.table):
  For each WO: WO header row (full-width) + 12 metric rows with processes as columns.

  Columns : [WO / Splits] [Metric] [Process-L] [Process-R] [Process-L] [Process-R] …
  Each process gets 2 sub-cols (left = start/in/WIP, right = end/out/fail).
  Metric rows:
    0  Target UPH           — blank (no MES target data)
    1  # Machine Used        — EQUIPMENT (merged across 2 sub-cols)
    2  Expected Work Hours   — blank
    3  Target Start / End    — blank | blank
    4  Actual Start / End    — MIN(BEGINTIME) | MAX(ENDTIME)
    5  Actual Work Hours     — MIN→MAX capped by calendar days×shift; StartRuncard: —
    6  Actual UPH            — finished ÷ max(Σ lot h, wall×mach, shift×mach); StartRuncard: —
    7  WO Input / Out        — qty_in (green) | qty_out (green)
    8  WIP / Fail            — 0 (grey)       | scrap+repair (orange)
    9  Yield                 — yield% (colored, merged)
   10  Target / Actual       — Target qty = UPH×mach×shift; StartRuncard: Target = WO Qty in
   11  Efficiency            — Pass÷Target×100; StartRuncard: Out÷In×100% (tooltip shows Out/In)
"""

from collections import defaultdict
from datetime import datetime
from typing import List, Dict, Optional

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QScrollArea,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont

from ..backend.data_models import (
    QueryResult, WorkOrderData, LotData, LotOperationData, OperationData,
)
from ..utils.constants import TARGET_YIELD
from ..utils import process_config

# MES route step — no line UPH; Target = WO Qty in, Efficiency shows Out/In.
_OP_START_RUNCARD = "StartRuncard"


def _hours_per_day_for_op(product_type: str, op_name: str) -> float:
    row = process_config.get(product_type, op_name) or {}
    h = float(row.get("work_hours", process_config._DEFAULT_WH) or 0.0)
    return h if h > 0 else float(process_config._DEFAULT_WH)

# ── Colours ───────────────────────────────────────────────────────────────────
_CLR_WO_HDR_BG  = "#1565C0"
_CLR_WO_HDR_FG  = "#FFFFFF"
_CLR_WO_MERGE   = "#BBDEFB"
_CLR_LABEL_BG   = "#F5F5F5"
_CLR_OP_HDR_BG  = "#E8EAF6"
_CLR_OP_HDR_FG  = "#0D47A1"
_CLR_SEPARATOR  = "#90A4AE"
_CLR_TOTALS_BG  = "#CFD8DC"
_CLR_IN_GREEN   = "#C8E6C9"
_CLR_OUT_GREEN  = "#A5D6A7"
_CLR_WIP_GREY   = "#B0BEC5"
_CLR_FAIL_ORG   = "#FFB74D"
_CLR_PASS       = "#1B5E20"
_CLR_FAIL_FG    = "#B71C1C"
_CLR_IN_PROG    = "#E65100"

_STATUS_COLOR = {
    "Created": "#1565C0", "Released": "#2E7D32",
    "Finished": "#424242", "Closed": "#424242", "On Hold": "#E65100",
}

_METRICS = [
    "Target UPH",
    "# Machine Used",
    "Expected Work Hours",
    "Target Start / End",
    "Actual Start / End",
    "Actual Work Hours",
    "Actual UPH",
    "WO Input / Out",
    "WIP / Fail",
    "Yield",
    "Target / Actual",
    "Efficiency",
]
_N_METRICS = len(_METRICS)

# Metric row indices
_R_TARGET_UPH   = 0
_R_MACHINE      = 1
_R_EXP_HRS      = 2
_R_TARGET_SE    = 3
_R_ACTUAL_SE    = 4
_R_ACT_HRS      = 5
_R_ACT_UPH      = 6
_R_INPUT_OUT    = 7
_R_WIP_FAIL     = 8
_R_YIELD        = 9
_R_TGT_ACTUAL   = 10
_R_EFFICIENCY   = 11


def _yield_fg(y: float) -> QColor:
    return QColor("#2E7D32" if y >= TARGET_YIELD else ("#E65100" if y >= 80 else "#C62828"))

def _yield_bg(y: float) -> QColor:
    return QColor("#E8F5E9" if y >= TARGET_YIELD else ("#FFF3E0" if y >= 80 else "#FFEBEE"))

def _fmt_dt(dt) -> str:
    if dt is None:
        return ""
    try:
        return dt.strftime("%m/%d %H:%M")
    except Exception:
        return str(dt)

def _hhmm(hours: float) -> str:
    h = int(hours)
    m = int(round((hours - h) * 60))
    return f"{h}:{m:02d}"


class WOScheduleTab(QWidget):
    @staticmethod
    def _calendar_days_inclusive(t0: datetime, t1: datetime) -> int:
        """Inclusive calendar-day count from first start date to last end date."""
        if t1 <= t0:
            return 1
        return (t1.date() - t0.date()).days + 1

    @staticmethod
    def _scheduled_duration_cap_hours(
        t0: Optional[datetime],
        t1: Optional[datetime],
        raw_hours: float,
        hours_per_day: float,
    ) -> float:
        """Cap a raw hour span so each calendar day counts at most ``hours_per_day``.

        MES BEGINTIME→ENDTIME can span nights idle; this matches “only count ~7 h per day”
        for KPI denominators without using INTIME/OUTTIME.
        """
        raw = max(float(raw_hours or 0.0), 0.0)
        hpd = max(float(hours_per_day or 0.0), 0.0)
        if hpd <= 0:
            hpd = float(process_config._DEFAULT_WH)
        if t0 is None or t1 is None:
            return raw
        try:
            if t1 <= t0:
                return min(raw, hpd)
            n_days = WOScheduleTab._calendar_days_inclusive(t0, t1)
        except (TypeError, AttributeError):
            return raw
        return min(raw, float(n_days) * hpd)

    @staticmethod
    def _uph_capacity_hours(
        work_hrs: float,
        lot_hours: float,
        n_machines: float,
        plan_shift_hrs: float = 0.0,
    ) -> float:
        """Denominator hours for Actual UPH: max(Σ lot_hours, work_hrs×machines, shift×machines)."""
        nm = max(float(n_machines or 0.0), 1.0)
        wh = max(float(work_hrs or 0.0), 0.0)
        lh = max(float(lot_hours or 0.0), 0.0)
        ph = max(float(plan_shift_hrs or 0.0), 0.0)
        return max(lh, wh * nm, ph * nm)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 12, 0, 0)
        outer.setSpacing(0)

        self._placeholder = QLabel("Run a query to view the WO schedule tracker.")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color: #9E9E9E; font-size: 13px;")
        outer.addWidget(self._placeholder)

        # Single scroll area that holds both tables stacked vertically
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.hide()

        self._scroll_widget = QWidget()
        layout = QVBoxLayout(self._scroll_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self._scroll.setWidget(self._scroll_widget)
        outer.addWidget(self._scroll, stretch=1)

        # Top: compact per-WO summary
        self.summary_table = QTableWidget()
        self.summary_table.setAlternatingRowColors(True)
        self.summary_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.summary_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.summary_table.setSortingEnabled(False)
        self.summary_table.verticalHeader().setVisible(False)
        self.summary_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.summary_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.summary_table)

        # Bottom: Excel-style matrix (no internal scroll — outer scroll area handles it)
        self.table = QTableWidget()
        self.table.setAlternatingRowColors(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSortingEnabled(False)
        self.table.verticalHeader().setVisible(False)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self.table)
        layout.addStretch()

    # ── Public API ────────────────────────────────────────────────────────────

    def update_result(self, result: QueryResult):
        self._placeholder.hide()
        self._scroll.show()

        params     = result.query_params
        start_date = getattr(params, "start_date", None) if params else None
        end_date   = getattr(params, "end_date",   None) if params else None

        wos        = result.work_orders
        op_history = result.operation_history
        lots       = result.lot_tracking
        lot_ops    = result.lot_operations
        product_type = params.product_type if params else ""

        ops_ordered = self._route_order(op_history)
        lot_op_map  = self._build_lot_op_map(lot_ops)
        wo_lots     = self._filter_lots(lots, lot_op_map, start_date, end_date)
        wo_op_agg   = self._aggregate(
            wos, wo_lots, lot_op_map, op_history, start_date, end_date, product_type
        )
        wo_op_wip   = self._compute_wip(lot_ops, lots)
        self._build_summary(wos, ops_ordered, wo_op_agg, wo_lots)
        self._build_matrix(wos, ops_ordered, wo_op_agg, wo_lots, wo_op_wip, product_type)

    def reset(self):
        self._scroll.hide()
        for t in (self.summary_table, self.table):
            t.clearContents(); t.setRowCount(0)
        self._placeholder.show()

    # ── Shared helpers ────────────────────────────────────────────────────────

    def _route_order(self, op_history: List[OperationData]) -> List[str]:
        seen: set = set()
        out: List[str] = []
        for op in sorted(op_history, key=lambda x: x.op_seq):
            if op.operation and op.operation not in seen:
                out.append(op.operation)
                seen.add(op.operation)
        return out

    def _build_lot_op_map(self, lot_ops: List[LotOperationData]) -> Dict[str, Dict[str, LotOperationData]]:
        m: Dict[str, Dict[str, LotOperationData]] = defaultdict(dict)
        for lo in lot_ops:
            m[lo.lot][lo.operation] = lo
        return m

    def _filter_lots(self, lots, lot_op_map, start_date, end_date) -> Dict[str, List[LotData]]:
        wo_lots: Dict[str, List[LotData]] = defaultdict(list)
        for lot in lots:
            wo_lots[lot.wo].append(lot)

        def _in_range(lot: LotData) -> bool:
            ops = lot_op_map.get(lot.lot, {}).values()
            if not ops:
                return False
            if start_date is None or end_date is None:
                return True
            for lo in ops:
                for t_val in (lo.start_time, lo.end_time):
                    if t_val is None:
                        continue
                    d = t_val.date() if hasattr(t_val, "date") else t_val
                    if start_date <= d <= end_date:
                        return True
            return False

        for wo_num in wo_lots:
            wo_lots[wo_num] = sorted(
                [l for l in wo_lots[wo_num] if _in_range(l)],
                key=lambda l: max(
                    (t for lo in lot_op_map.get(l.lot, {}).values()
                     for t in (lo.start_time, lo.end_time) if t is not None),
                    default=datetime.min
                )
            )
        return wo_lots

    def _aggregate(self, wos, wo_lots, lot_op_map, op_history,
                   start_date=None, end_date=None, product_type: str = "") -> Dict[str, Dict[str, dict]]:
        """Per-WO per-operation aggregation.

        Inclusion: start_time OR end_time within [start_date, end_date].

        units     — N In:  started in range
        carry_in  — started before range but completed in range (adds to N Out, not N In)
        range_wip — started in range but not completed in range
        scrap / repair — attributed only to lots that completed in range
        lot_hours — sum over contributing (lot,op) of min(raw step hours,
                    #calendar_days(start,end) × station Work Hours for that op);
                    parallel lots still add; each step is capped vs 24/7 soak.
        """
        def _dt_in_range(dt) -> bool:
            if dt is None:
                return False
            if start_date is None or end_date is None:
                return True
            d = dt.date() if hasattr(dt, "date") else dt
            return start_date <= d <= end_date

        wo_op_agg: Dict[str, Dict[str, dict]] = {w.wo_number: {} for w in wos}
        for wo_num, lot_list in wo_lots.items():
            if wo_num not in wo_op_agg:
                continue
            for lot in lot_list:
                for op_name, lo in lot_op_map.get(lot.lot, {}).items():
                    start_ok = _dt_in_range(lo.start_time)
                    end_ok   = _dt_in_range(lo.end_time)
                    if not start_ok and not end_ok:
                        continue

                    agg = wo_op_agg[wo_num].setdefault(op_name, {
                        "splits": 0, "units": 0, "carry_in": 0,
                        "scrap": 0, "repair": 0, "range_wip": 0,
                        "starts": [], "ends": [], "equipment": set(),
                        "lot_hours": 0.0,
                    })
                    agg["splits"] += 1

                    if lo.start_time and lo.end_time:
                        dh_raw = (lo.end_time - lo.start_time).total_seconds() / 3600.0
                        if dh_raw > 0:
                            hpd = _hours_per_day_for_op(product_type, op_name)
                            dh = WOScheduleTab._scheduled_duration_cap_hours(
                                lo.start_time, lo.end_time, dh_raw, hpd
                            )
                            agg["lot_hours"] += dh

                    if start_ok:
                        agg["units"]  += lo.unit_count
                        agg["starts"].append(lo.start_time)
                        if not end_ok:
                            agg["range_wip"] += lo.unit_count
                    else:
                        # Started before range, finished in range — carry-in output
                        agg["carry_in"] += lo.unit_count

                    if end_ok:
                        agg["scrap"]  += lo.scrap_count
                        agg["repair"] += lo.repair_count
                        agg["ends"].append(lo.end_time)

                    if lo.equipment:
                        agg["equipment"].add(lo.equipment)
        return wo_op_agg

    def _compute_wip(
        self, lot_ops: List[LotOperationData], lots: List[LotData]
    ) -> Dict[str, Dict[str, int]]:
        """Per-WO per-op unit count currently in progress (started, not yet completed)."""
        result: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        lot_to_wo: Dict[str, str] = {lot.lot: lot.wo for lot in lots}
        for lo in lot_ops:
            if lo.start_time is not None and lo.end_time is None:
                wo = lot_to_wo.get(lo.lot)
                if wo:
                    result[wo][lo.operation] += lo.unit_count
        return result

    @staticmethod
    def _fit_table_height(t: QTableWidget):
        """Expand table to its full row height so the outer scroll area handles scrolling."""
        h = t.horizontalHeader().height() + sum(t.rowHeight(r) for r in range(t.rowCount())) + 4
        t.setFixedHeight(h)

    # ── Summary table ─────────────────────────────────────────────────────────

    def _build_summary(self, wos, ops_ordered, wo_op_agg, wo_lots):
        """Totals row + one row per WO: WO | Start | End | process yields | Overall Yield"""
        t = self.summary_table
        t.clearContents(); t.setRowCount(0)

        n_ops  = len(ops_ordered)
        n_cols = 3 + n_ops + 1
        yld_c  = 3 + n_ops

        t.setColumnCount(n_cols)
        t.setHorizontalHeaderLabels(["WO", "Start Time", "End Time"] + ops_ordered + ["Overall Yield"])
        bold = QFont(); bold.setBold(True)
        for c in range(3, 3 + n_ops):
            hdr = t.horizontalHeaderItem(c)
            if hdr:
                hdr.setBackground(QColor(_CLR_OP_HDR_BG))
                hdr.setForeground(QColor(_CLR_OP_HDR_FG))

        # Grand aggregate
        grand: Dict[str, dict] = {}
        for wo_agg in wo_op_agg.values():
            for op, agg in wo_agg.items():
                g = grand.setdefault(op, {
                    "splits": 0, "units": 0, "carry_in": 0, "range_wip": 0,
                    "scrap": 0, "repair": 0, "starts": [], "ends": [], "lot_hours": 0.0,
                })
                g["splits"]    += agg["splits"];              g["units"]    += agg["units"]
                g["carry_in"]  += agg.get("carry_in", 0);    g["range_wip"]+= agg.get("range_wip", 0)
                g["scrap"]     += agg["scrap"];               g["repair"]   += agg["repair"]
                g["starts"]    += agg["starts"];              g["ends"]     += agg["ends"]
                g["lot_hours"] += float(agg.get("lot_hours", 0.0) or 0.0)

        total_splits   = sum(len(v) for v in wo_lots.values())
        all_gs = [s for g in grand.values() for s in g["starts"]]
        all_ge = [e for g in grand.values() for e in g["ends"]]

        t.setRowCount(1 + len(wos))

        def _c(text, fg=None, bg=None, tip=None, font=None):
            item = QTableWidgetItem(text)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if fg:   item.setForeground(QColor(fg))
            if bg:   item.setBackground(QColor(bg))
            if tip:  item.setToolTip(tip)
            if font: item.setFont(font)
            return item

        # Row 0 — totals
        t.setRowHeight(0, 30)
        label = f"{len(wos)} WO{'s' if len(wos)!=1 else ''}  |  {total_splits} Split{'s' if total_splits!=1 else ''}"
        t.setItem(0, 0, _c(label, bg=_CLR_TOTALS_BG, font=bold))
        t.setItem(0, 1, _c(_fmt_dt(min(all_gs)) if all_gs else "", bg=_CLR_TOTALS_BG, font=bold))
        t.setItem(0, 2, _c(_fmt_dt(max(all_ge)) if all_ge else "", bg=_CLR_TOTALS_BG, font=bold))
        for ci, op in enumerate(ops_ordered):
            c = 3 + ci; g = grand.get(op)
            if not g or (g["units"] == 0 and g.get("carry_in", 0) == 0):
                t.setItem(0, c, _c("", bg=_CLR_TOTALS_BG)); continue
            completed = (g["units"] - g.get("range_wip", 0)) + g.get("carry_in", 0)
            pu = max(0, completed - g["scrap"] - g["repair"])
            n_in = g["units"] or 1
            py = round(pu / n_in * 100, 1)
            tip = (f"Total splits: {g['splits']}\nQty in: {g['units']:,}\n"
                   f"Carry-in: {g.get('carry_in',0):,}\nWIP: {g.get('range_wip',0):,}\n"
                   f"Pass: {pu:,}\nScrap: {g['scrap']:,}\nRepair: {g['repair']:,}")
            fg  = _CLR_PASS if py >= TARGET_YIELD else (_CLR_IN_PROG if py >= 80 else _CLR_FAIL_FG)
            t.setItem(0, c, _c(f"{py:.1f}%", fg=fg, bg=_CLR_TOTALS_BG, tip=tip, font=bold))
        avg_y = round(sum(w.yield_pct for w in wos)/len(wos),1) if wos else 0.0
        yi = _c(f"{avg_y:.1f}%", font=bold)
        yi.setForeground(_yield_fg(avg_y)); yi.setBackground(_yield_bg(avg_y))
        t.setItem(0, yld_c, yi)

        # Rows 1+ — per WO
        for row, wo in enumerate(wos, 1):
            t.setRowHeight(row, 24)
            agg_by_op = wo_op_agg.get(wo.wo_number, {})
            all_s = [s for a in agg_by_op.values() for s in a["starts"]]
            all_e = [e for a in agg_by_op.values() for e in a["ends"]]
            ns    = len(wo_lots.get(wo.wo_number, []))
            lbl   = f"{wo.wo_number}  ({ns} split{'s' if ns!=1 else ''})"
            t.setItem(row, 0, _c(lbl, fg=_STATUS_COLOR.get(wo.status,"#424242"), font=bold))
            t.setItem(row, 1, _c(_fmt_dt(min(all_s)) if all_s else ""))
            t.setItem(row, 2, _c(_fmt_dt(max(all_e)) if all_e else "—"))
            for ci, op in enumerate(ops_ordered):
                c = 3 + ci; agg = agg_by_op.get(op)
                if not agg or (agg["units"]==0 and agg.get("carry_in",0)==0):
                    t.setItem(row, c, _c("")); continue
                completed = (agg["units"] - agg.get("range_wip", 0)) + agg.get("carry_in", 0)
                pu = max(0, completed - agg["scrap"] - agg["repair"])
                n_in = agg["units"] or 1
                py = round(pu / n_in * 100, 1)
                tip = f"Splits: {agg['splits']}\nQty in: {agg['units']:,}\nPass: {pu:,}\nScrap: {agg['scrap']:,}\nRepair: {agg['repair']:,}"
                fg = _CLR_PASS if py>=TARGET_YIELD else (_CLR_IN_PROG if py>=80 else _CLR_FAIL_FG)
                bg = "#E8F5E9" if py>=TARGET_YIELD else ("#FFF3E0" if py>=80 else "#FFEBEE")
                t.setItem(row, c, _c(f"{py:.1f}%", fg=fg, bg=bg, tip=tip))
            yi = _c(f"{wo.yield_pct:.1f}%", font=bold)
            yi.setForeground(_yield_fg(wo.yield_pct)); yi.setBackground(_yield_bg(wo.yield_pct))
            t.setItem(row, yld_c, yi)

        t.resizeColumnsToContents()
        t.setColumnWidth(0, max(160, t.columnWidth(0)))
        self._fit_table_height(t)

    # ── Matrix table ──────────────────────────────────────────────────────────

    def _build_matrix(self, wos, ops_ordered, wo_op_agg, wo_lots, wo_op_wip, product_type=""):
        """Excel-style: rows = metrics, columns = processes (3 sub-cols each)."""
        t = self.table
        try:
            t.cellChanged.disconnect(self._on_matrix_cell_changed)
        except (RuntimeError, TypeError):
            pass
        t.clearContents(); t.setRowCount(0)

        n_ops  = len(ops_ordered)
        n_cols = 2 + n_ops * 3     # [WO/Splits] [Metric] [Op-L Op-M Op-R] …
        t.setColumnCount(n_cols)

        # Column headers: process name on first sub-col, blanks for M and R
        hdrs = ["WO / Splits", "Metric"]
        for op in ops_ordered:
            hdrs += [op, "", ""]
        t.setHorizontalHeaderLabels(hdrs)
        for ci in range(n_ops):
            hdr = t.horizontalHeaderItem(2 + ci * 3)
            if hdr:
                hdr.setBackground(QColor(_CLR_OP_HDR_BG))
                hdr.setForeground(QColor(_CLR_OP_HDR_FG))

        bold   = QFont(); bold.setBold(True)
        sm_b   = QFont(); sm_b.setBold(True); sm_b.setPointSize(8)
        wo_fnt = QFont(); wo_fnt.setBold(True); wo_fnt.setPointSize(9)

        def _c(text, fg=None, bg=None, font=None, align=Qt.AlignmentFlag.AlignCenter):
            item = QTableWidgetItem(text)
            item.setTextAlignment(align)
            if fg:   item.setForeground(QColor(fg))
            if bg:   item.setBackground(QColor(bg))
            if font: item.setFont(font)
            return item

        # ── Grand-total block (top of matrix) ────────────────────────────────
        total_wos    = len(wos)
        total_splits = sum(len(v) for v in wo_lots.values())
        total_qty    = sum(w.total_qty for w in wos)

        # Aggregate across all WOs per operation (date-range activity)
        grand_agg: Dict[str, dict] = {}
        for wo_agg in wo_op_agg.values():
            for op, agg in wo_agg.items():
                g = grand_agg.setdefault(op, {
                    "units": 0, "carry_in": 0, "range_wip": 0,
                    "scrap": 0, "repair": 0,
                    "starts": [], "ends": [], "equipment": set(),
                    "lot_hours": 0.0,
                })
                g["units"]      += agg["units"]
                g["carry_in"]   += agg.get("carry_in", 0)
                g["range_wip"]  += agg.get("range_wip", 0)
                g["scrap"]      += agg["scrap"]
                g["repair"]     += agg["repair"]
                g["starts"]     += agg["starts"]
                g["ends"]       += agg["ends"]
                g["equipment"]  |= agg["equipment"]
                g["lot_hours"]  += float(agg.get("lot_hours", 0.0) or 0.0)

        # Aggregate WIP across all WOs per operation
        grand_wip: Dict[str, int] = defaultdict(int)
        for wo_wip in wo_op_wip.values():
            for op, cnt in wo_wip.items():
                grand_wip[op] += cnt

        self._insert_wo_block(
            t, n_cols, bold, sm_b, wo_fnt, ops_ordered,
            header_text=(f"  TOTAL    "
                         f"WOs: {total_wos}    "
                         f"Splits: {total_splits}    "
                         f"Total Qty: {total_qty:,}"),
            header_bg=_CLR_TOTALS_BG, header_fg="#000000",
            split_label=f"{total_wos} WOs\n{total_splits} Splits",
            agg_by_op=grand_agg,
            wip_by_op=dict(grand_wip),
            product_type=product_type,
        )

        # Separator after grand total
        sep_r = t.rowCount()
        t.insertRow(sep_r); t.setRowHeight(sep_r, 6)
        for c in range(n_cols):
            sep = QTableWidgetItem(""); sep.setBackground(QColor(_CLR_SEPARATOR))
            t.setItem(sep_r, c, sep)

        for wo_idx, wo in enumerate(wos):
            n_splits  = len(wo_lots.get(wo.wo_number, []))
            self._insert_wo_block(
                t, n_cols, bold, sm_b, wo_fnt, ops_ordered,
                header_text=(f"  {wo.wo_number}    "
                             f"Qty: {wo.total_qty:,}    "
                             f"Status: {wo.status or '—'}    "
                             f"Schedule: {wo.schedule_date or wo.end_date}    "
                             f"Splits: {n_splits}    "
                             f"Overall Yield: {wo.yield_pct:.1f}%"),
                header_bg=_CLR_WO_HDR_BG, header_fg=_CLR_WO_HDR_FG,
                split_label=f"{n_splits}\nsplit{'s' if n_splits!=1 else ''}",
                agg_by_op=wo_op_agg.get(wo.wo_number, {}),
                wip_by_op=dict(wo_op_wip.get(wo.wo_number, {})),
                product_type=product_type,
            )
            if wo_idx < len(wos) - 1:
                sep_r = t.rowCount()
                t.insertRow(sep_r); t.setRowHeight(sep_r, 4)
                for c in range(n_cols):
                    sep = QTableWidgetItem("")
                    sep.setBackground(QColor(_CLR_SEPARATOR))
                    t.setItem(sep_r, c, sep)

        # Wire up live recalculation when user edits Target UPH or # Machines
        t.cellChanged.connect(self._on_matrix_cell_changed)

        t.resizeColumnsToContents()
        t.setColumnWidth(0, max(80,  t.columnWidth(0)))
        t.setColumnWidth(1, max(140, t.columnWidth(1)))
        self._fit_table_height(t)

    def _on_matrix_cell_changed(self, row: int, col: int):
        """Recalculate Expected Hours, Target/Actual and Efficiency when user edits Target UPH or # Machines."""
        t = self.table
        item = t.item(row, col)
        if item is None:
            return
        meta = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(meta, dict) or meta.get("type") not in ("target_uph", "n_machines"):
            return

        lc           = meta["lc"]
        mc           = meta["mc"]
        first_r      = meta["first_r"]
        cfg_work_hrs = meta.get("cfg_work_hrs", process_config._DEFAULT_WH)
        pass_u       = meta["pass_u"]
        completed    = int(meta.get("completed", pass_u))
        work_hrs_raw = meta.get("work_hrs_raw")
        ws           = meta.get("wall_start")
        we           = meta.get("wall_end")
        if work_hrs_raw is not None and ws is not None and we is not None:
            work_hrs = WOScheduleTab._scheduled_duration_cap_hours(
                ws, we, float(work_hrs_raw), float(cfg_work_hrs or 0.0)
            )
        else:
            work_hrs     = float(meta.get("work_hrs") or 0.0)

        lot_hours    = float(meta.get("lot_hours") or 0.0)

        bold = QFont(); bold.setBold(True)

        def _read_float(r, c) -> Optional[float]:
            it = t.item(r, c)
            if it is None: return None
            try: return float(it.text().replace(",", ""))
            except ValueError: return None

        target_uph = _read_float(first_r + _R_TARGET_UPH, lc)
        n_machines = _read_float(first_r + _R_MACHINE,     lc)
        op_name = str(meta.get("operation", "") or "")
        is_sr = op_name.strip() == _OP_START_RUNCARD

        t.blockSignals(True)
        try:
            nm = max(float(n_machines or 0.0), 1.0)
            # Row 6 — keep in sync when Target UPH or # machines is edited
            t.setSpan(first_r + _R_ACT_UPH, lc, 1, 3)
            if is_sr:
                up_it = QTableWidgetItem("—")
                up_it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                up_it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                up_it.setToolTip("StartRuncard — no Actual UPH; Efficiency shows Out÷In as % (see tooltip).")
                t.setItem(first_r + _R_ACT_UPH, lc, up_it)
            else:
                den = WOScheduleTab._uph_capacity_hours(work_hrs, lot_hours, nm, cfg_work_hrs)
                if den > 0:
                    uph_val = completed / den
                    uph_text = f"{uph_val:,.1f}"
                    uph_tip = (
                        "Finished ÷ max(Σ lot h, wall×mach, shift×mach).\n"
                        f"Finished = {completed:,} ÷ cap_h = {den:.3f} h\n"
                        f"(Σ lot = {lot_hours:.3f}; wall×mach = {work_hrs*nm:.3f}; "
                        f"shift×mach = {cfg_work_hrs*nm:.3f})"
                    )
                else:
                    uph_text = "—"
                    uph_tip = ""
                up_it = QTableWidgetItem(uph_text)
                up_it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                up_it.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                if uph_tip:
                    up_it.setToolTip(uph_tip)
                t.setItem(first_r + _R_ACT_UPH, lc, up_it)

            self._fill_derived_cells(
                t, first_r, lc, mc, bold,
                target_uph, n_machines, cfg_work_hrs,
                completed=completed,
                pass_u=pass_u,
                actual_work_hrs=work_hrs,
                lot_hours=lot_hours,
                operation_name=str(meta.get("operation", "") or ""),
                units_in=int(meta.get("units", 0) or 0),
            )
        finally:
            t.blockSignals(False)

    def _fill_derived_cells(
        self,
        t: QTableWidget,
        first_r: int,
        lc: int,
        mc: int,
        bold: QFont,
        target_uph: Optional[float],
        n_machines: Optional[float],
        cfg_work_hrs: float,
        completed: int,
        pass_u: int,
        actual_work_hrs: float = 0.0,
        lot_hours: float = 0.0,
        operation_name: str = "",
        units_in: int = 0,
    ):
        """Fill Expected Work Hours, Target (lc), and Efficiency.

        StartRuncard: Target = WO Qty in; Efficiency = Out ÷ In × 100% (same as Yield for this step);
        tooltip shows Out / In counts. No time-based KPI rows.

        Other ops: Target qty = Target UPH × # machines × Expected Work Hours (one nominal shift).
        Efficiency = Pass ÷ Target qty × 100.

        Actual UPH row uses completed ÷ _uph_capacity_hours (lot / capped wall / shift).
        Wall and per-lot MES spans are first capped to calendar days × station Work Hours.
        """
        is_sr = (operation_name or "").strip() == _OP_START_RUNCARD

        if is_sr:
            t.setSpan(first_r + _R_EXP_HRS, lc, 1, 3)
            exp_item = QTableWidgetItem("—")
            exp_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            exp_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            t.setItem(first_r + _R_EXP_HRS, lc, exp_item)

            n_in = max(int(units_in or 0), 0)
            ta_item = QTableWidgetItem(f"{n_in:,}" if n_in > 0 else "—")
            ta_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            ta_item.setBackground(QColor(_CLR_LABEL_BG))
            ta_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            t.setItem(first_r + _R_TGT_ACTUAL, lc, ta_item)

            t.setSpan(first_r + _R_EFFICIENCY, lc, 1, 3)
            if n_in > 0:
                eff_pct = round(pass_u / n_in * 100, 1)
                eff_item = QTableWidgetItem(f"{eff_pct:.1f}%")
                eff_item.setToolTip(
                    f"StartRuncard — Out ÷ In × 100 = {eff_pct:.1f}%\n"
                    f"Out / In = {pass_u:,} / {n_in:,}\n"
                    f"Target (left) = Qty in = {n_in:,}. No time-based throughput KPI for this step."
                )
                e_fg = _CLR_PASS if eff_pct >= 100 else (_CLR_IN_PROG if eff_pct >= 80 else _CLR_FAIL_FG)
                e_bg = "#E8F5E9" if eff_pct >= 100 else ("#FFF3E0" if eff_pct >= 80 else "#FFEBEE")
            else:
                eff_item = QTableWidgetItem("—")
                e_fg, e_bg = "#757575", "#F5F5F5"
            eff_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            eff_item.setForeground(QColor(e_fg))
            eff_item.setBackground(QColor(e_bg))
            eff_item.setFont(bold)
            eff_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            t.setItem(first_r + _R_EFFICIENCY, lc, eff_item)
            _ = mc
            return

        if target_uph and target_uph > 0 and n_machines and n_machines > 0:
            # Expected Work Hours = configured shift hours from Station Information
            t.setSpan(first_r + _R_EXP_HRS, lc, 1, 3)
            exp_item = QTableWidgetItem(_hhmm(cfg_work_hrs))
            exp_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            exp_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            t.setItem(first_r + _R_EXP_HRS, lc, exp_item)

            plan_h = max(float(cfg_work_hrs or 0.0), 0.0)

            if plan_h > 0:
                target_qty = round(target_uph * n_machines * plan_h)

                ta_item = QTableWidgetItem(f"{target_qty:,}" if target_qty > 0 else "—")
                ta_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                ta_item.setBackground(QColor(_CLR_LABEL_BG))
                ta_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                t.setItem(first_r + _R_TGT_ACTUAL, lc, ta_item)

                t.setSpan(first_r + _R_EFFICIENCY, lc, 1, 3)
                cap_h = WOScheduleTab._uph_capacity_hours(
                    float(actual_work_hrs or 0.0),
                    float(lot_hours or 0.0),
                    float(n_machines or 0.0),
                    plan_h,
                )
                actual_uph = (completed / cap_h) if cap_h > 0 else 0.0
                if target_qty > 0:
                    eff = round(pass_u / target_qty * 100, 1)
                    e_tip = (
                        f"Pass {pass_u:,} ÷ Target qty {target_qty:,} × 100\n"
                        f"(Target qty = Target UPH × machines × {plan_h:.2f} h shift)\n"
                        f"Actual UPH (ref): {actual_uph:,.2f} (finished ÷ cap_h={cap_h:.3f} h)"
                    )
                    e_fg = _CLR_PASS if eff >= 100 else (_CLR_IN_PROG if eff >= 80 else _CLR_FAIL_FG)
                    e_bg = "#E8F5E9" if eff >= 100 else ("#FFF3E0" if eff >= 80 else "#FFEBEE")
                    eff_item = QTableWidgetItem(f"{eff:.1f}%")
                    eff_item.setToolTip(e_tip)
                else:
                    eff_item = QTableWidgetItem("—")
                    e_fg, e_bg = "#757575", "#F5F5F5"
                eff_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                eff_item.setForeground(QColor(e_fg))
                eff_item.setBackground(QColor(e_bg))
                eff_item.setFont(bold)
                eff_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                t.setItem(first_r + _R_EFFICIENCY, lc, eff_item)
            else:
                # No shift length — cannot align Target/Efficiency
                clr_t = QTableWidgetItem("—")
                clr_t.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                clr_t.setBackground(QColor(_CLR_LABEL_BG))
                clr_t.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                t.setItem(first_r + _R_TGT_ACTUAL, lc, clr_t)
                t.setSpan(first_r + _R_EFFICIENCY, lc, 1, 3)
                clr_e = QTableWidgetItem("—")
                clr_e.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                clr_e.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                t.setItem(first_r + _R_EFFICIENCY, lc, clr_e)
        else:
            for row_offset, span in ((_R_EXP_HRS, 3), (_R_EFFICIENCY, 3)):
                t.setSpan(first_r + row_offset, lc, 1, span)
                clr = QTableWidgetItem("—")
                clr.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                clr.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
                t.setItem(first_r + row_offset, lc, clr)
            clr3 = QTableWidgetItem("—")
            clr3.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            clr3.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            t.setItem(first_r + _R_TGT_ACTUAL, lc, clr3)
            _ = mc

    # ── Per-WO block renderer ─────────────────────────────────────────────────

    def _insert_wo_block(
        self,
        t: QTableWidget,
        n_cols: int,
        bold: QFont,
        sm_b: QFont,
        wo_fnt: QFont,
        ops_ordered: List[str],
        *,
        header_text: str,
        header_bg: str,
        header_fg: str,
        split_label: str,
        agg_by_op: Dict[str, dict],
        wip_by_op: Optional[Dict[str, int]] = None,
        product_type: str = "",
    ):
        def _ro(text, fg=None, bg=None, font=None, align=Qt.AlignmentFlag.AlignCenter, tooltip=""):
            """Read-only table item."""
            item = QTableWidgetItem(text)
            item.setTextAlignment(align)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            if fg:   item.setForeground(QColor(fg))
            if bg:   item.setBackground(QColor(bg))
            if font: item.setFont(font)
            if tooltip:
                item.setToolTip(tooltip)
            return item

        def _ed(text, meta=None, tooltip=""):
            """Editable table item with optional UserRole metadata."""
            item = QTableWidgetItem(text)
            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if meta:    item.setData(Qt.ItemDataRole.UserRole, meta)
            if tooltip: item.setToolTip(tooltip)
            return item

        # ── WO header row ─────────────────────────────────────────────────────
        hdr_r = t.rowCount()
        t.insertRow(hdr_r)
        t.setRowHeight(hdr_r, 28)
        hdr_item = QTableWidgetItem(f"  {header_text}")
        hdr_item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        hdr_item.setFont(wo_fnt)
        hdr_item.setForeground(QColor(header_fg))
        hdr_item.setBackground(QColor(header_bg))
        hdr_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
        t.setItem(hdr_r, 0, hdr_item)
        t.setSpan(hdr_r, 0, 1, n_cols)

        # ── Metric rows ───────────────────────────────────────────────────────
        first_r = t.rowCount()
        for _ in range(_N_METRICS):
            r = t.rowCount()
            t.insertRow(r)
            t.setRowHeight(r, 26)

        # Col 0: merged WO/Splits label
        t.setSpan(first_r, 0, _N_METRICS, 1)
        wo_cell = _ro(split_label, font=bold, bg=_CLR_WO_MERGE)
        t.setItem(first_r, 0, wo_cell)

        # Col 1: metric labels
        for mi, label in enumerate(_METRICS):
            lbl = _ro(f"  {label}", bg=_CLR_LABEL_BG, font=sm_b,
                      align=Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
            t.setItem(first_r + mi, 1, lbl)

        # Cols 2+: per-operation data  (3 sub-cols: lc=left, mc=mid, rc=right)
        _global_wip = wip_by_op or {}
        for ci, op in enumerate(ops_ordered):
            lc = 2 + ci * 3
            mc = lc + 1
            rc = lc + 2
            agg = agg_by_op.get(op)
            # Use date-range WIP when there is in-range activity; fall back to
            # global WIP (end_time IS NULL) for processes with no in-range starts.
            wip_ct = agg.get("range_wip", 0) if agg else _global_wip.get(op, 0)

            if not agg or agg.get("units", 0) == 0:
                for mi in range(_N_METRICS):
                    t.setItem(first_r + mi, lc, _ro("—"))
                    t.setItem(first_r + mi, mc, _ro(""))
                    t.setItem(first_r + mi, rc, _ro(""))
                if wip_ct > 0:
                    # Show opening WIP even though no in-range activity
                    t.setItem(first_r + _R_WIP_FAIL, lc,
                              _ro(f"{wip_ct:,}", bg=_CLR_WIP_GREY))
                    t.setSpan(first_r + _R_TGT_ACTUAL, mc, 1, 2)
                    t.setItem(first_r + _R_TGT_ACTUAL, mc,
                              _ro(f"{wip_ct:,}", bg=_CLR_WIP_GREY))
                continue

            units     = agg["units"]                               # N In — started in range
            carry_in  = agg.get("carry_in", 0)                    # started before range, finished in range
            range_wip = agg.get("range_wip", 0)                   # started in range, not finished
            scrap     = agg["scrap"]
            repair    = agg["repair"]
            completed = (units - range_wip) + carry_in             # finished within range
            pass_u    = max(0, completed - scrap - repair)         # N Out
            fail_u    = scrap + repair
            eq     = ", ".join(sorted(agg.get("equipment", set()))) or ""

            starts  = agg.get("starts", [])
            ends    = agg.get("ends",   [])
            min_st  = min(starts) if starts else None
            max_end = max(ends)   if ends   else None

            _cfg      = process_config.get(product_type, op) or {}
            _uph_val  = _cfg.get("target_uph",  process_config._DEFAULT_UPH)
            _mac_val  = _cfg.get("machines",     process_config._DEFAULT_MACHINES)
            _wh_val   = _cfg.get("work_hours",   process_config._DEFAULT_WH)
            _hpd      = float(_wh_val or 0.0) or float(process_config._DEFAULT_WH)

            if min_st and max_end:
                work_hrs_raw = (max_end - min_st).total_seconds() / 3600
                work_hrs = WOScheduleTab._scheduled_duration_cap_hours(
                    min_st, max_end, work_hrs_raw, _hpd
                )
            else:
                work_hrs_raw = 0.0
                work_hrs = 0.0

            proc_yield = round(pass_u / units * 100, 1) if units else 0.0

            # Metadata for live recalc (stored in editable cells)
            base_meta = {
                "lc": lc, "mc": mc, "rc": rc, "first_r": first_r,
                "operation": op,
                "work_hrs": work_hrs,
                "work_hrs_raw": work_hrs_raw,
                "wall_start": min_st,
                "wall_end": max_end,
                "units": units, "pass_u": pass_u,
                "completed": completed,
                "cfg_work_hrs": _wh_val,
                "lot_hours": float(agg.get("lot_hours", 0.0) or 0.0),
            }

            # Row 0 — Target UPH (editable, spans all 3, pre-filled from config)
            t.setSpan(first_r + _R_TARGET_UPH, lc, 1, 3)
            t.setItem(first_r + _R_TARGET_UPH, lc,
                      _ed(str(int(_uph_val) if _uph_val == int(_uph_val) else _uph_val),
                          meta={**base_meta, "type": "target_uph"}))

            # Row 1 — # Machine Used (editable, pre-filled from config)
            t.setSpan(first_r + _R_MACHINE, lc, 1, 3)
            t.setItem(first_r + _R_MACHINE, lc,
                      _ed(str(int(_mac_val)), meta={**base_meta, "type": "n_machines"}, tooltip=eq))

            # Row 2 — Expected Work Hours (auto-calc, spans all 3, pre-filled if config available)
            t.setSpan(first_r + _R_EXP_HRS, lc, 1, 3)
            t.setItem(first_r + _R_EXP_HRS, lc, _ro("—"))

            # Row 3 — Target Start / End  (lc+mc = start, rc = end)
            t.setSpan(first_r + _R_TARGET_SE, lc, 1, 2)
            t.setItem(first_r + _R_TARGET_SE, lc, _ro("—"))
            t.setItem(first_r + _R_TARGET_SE, rc, _ro("—"))

            # Row 4 — Actual Start / End  (lc+mc = start, rc = end)
            t.setSpan(first_r + _R_ACTUAL_SE, lc, 1, 2)
            t.setItem(first_r + _R_ACTUAL_SE, lc, _ro(_fmt_dt(min_st)))
            t.setItem(first_r + _R_ACTUAL_SE, rc, _ro(_fmt_dt(max_end) if max_end else "—"))

            # Row 5 — Actual Work Hours (spans all 3); StartRuncard: no time KPI
            t.setSpan(first_r + _R_ACT_HRS, lc, 1, 3)
            if op == _OP_START_RUNCARD:
                act_h_item = _ro(
                    "—",
                    tooltip="StartRuncard is administrative — Actual Work Hours not used for KPIs.",
                )
            elif work_hrs > 0:
                _n_cal = WOScheduleTab._calendar_days_inclusive(min_st, max_end) if min_st and max_end else 1
                _hrs_tip = (
                    f"Counted: min(raw span, {_n_cal} calendar day(s) × {_hpd:g} h/day from station Work Hours). "
                    f"Raw MIN→MAX = {_hhmm(work_hrs_raw)} → shown {_hhmm(work_hrs)}."
                )
                act_h_item = _ro(_hhmm(work_hrs), tooltip=_hrs_tip)
            else:
                act_h_item = _ro("—")
            t.setItem(first_r + _R_ACT_HRS, lc, act_h_item)

            # Row 6 — Actual UPH; StartRuncard: no time KPI
            t.setSpan(first_r + _R_ACT_UPH, lc, 1, 3)
            if op == _OP_START_RUNCARD:
                t.setItem(
                    first_r + _R_ACT_UPH,
                    lc,
                    _ro(
                        "—",
                        tooltip="StartRuncard — no Actual UPH; Efficiency = Out÷In×100% (counts in tooltip).",
                    ),
                )
            else:
                _nm = max(float(_mac_val or 0.0), 1.0)
                _lh = float(agg.get("lot_hours", 0.0) or 0.0)
                _den = WOScheduleTab._uph_capacity_hours(work_hrs, _lh, _nm, _wh_val)
                if _den > 0:
                    uph_val = completed / _den
                    uph_text = f"{uph_val:,.1f}"
                    uph_tip = (
                        "Finished ÷ max(Σ lot h, wall×mach, shift×mach).\n"
                        f"Finished = {completed:,} ÷ cap_h = {_den:.3f} h\n"
                        f"(Σ lot = {_lh:.3f}; wall×mach = {work_hrs*_nm:.3f}; "
                        f"shift×mach = {_wh_val*_nm:.3f})"
                    )
                else:
                    uph_text = "—"
                    uph_tip = ""
                t.setItem(first_r + _R_ACT_UPH, lc, _ro(uph_text, tooltip=uph_tip))

            # Row 7 — WO Input / Out  (lc = input green, mc+rc = output green)
            t.setItem(first_r + _R_INPUT_OUT, lc,
                      _ro(f"{units:,}", bg=_CLR_IN_GREEN, font=bold))
            t.setSpan(first_r + _R_INPUT_OUT, mc, 1, 2)
            t.setItem(first_r + _R_INPUT_OUT, mc,
                      _ro(f"{pass_u:,}", bg=_CLR_OUT_GREEN, font=bold))

            # Row 8 — WIP / Fail  (lc = WIP grey, mc+rc = fail orange)
            t.setItem(first_r + _R_WIP_FAIL, lc,
                      _ro(f"{wip_ct:,}", bg=_CLR_WIP_GREY))
            t.setSpan(first_r + _R_WIP_FAIL, mc, 1, 2)
            t.setItem(first_r + _R_WIP_FAIL, mc,
                      _ro(f"{fail_u:,}", bg=_CLR_FAIL_ORG,
                          font=bold if fail_u > 0 else sm_b))

            # Row 9 — Yield (spans all 3, colored)
            t.setSpan(first_r + _R_YIELD, lc, 1, 3)
            y_item = _ro(f"{proc_yield:.1f}%", font=bold)
            y_item.setForeground(_yield_fg(proc_yield))
            y_item.setBackground(_yield_bg(proc_yield))
            t.setItem(first_r + _R_YIELD, lc, y_item)

            # Row 10 — Target / WIP / Actual  (lc=target, mc=WIP grey, rc=actual green)
            t.setItem(first_r + _R_TGT_ACTUAL, lc, _ro("—", bg=_CLR_LABEL_BG))
            t.setItem(first_r + _R_TGT_ACTUAL, mc,
                      _ro(f"{wip_ct:,}", bg=_CLR_WIP_GREY))
            t.setItem(first_r + _R_TGT_ACTUAL, rc,
                      _ro(f"{pass_u:,}", bg=_CLR_OUT_GREEN, font=bold))

            # Row 11 — Efficiency (spans all 3) — pre-calculated from config defaults
            t.setSpan(first_r + _R_EFFICIENCY, lc, 1, 3)
            t.setItem(first_r + _R_EFFICIENCY, lc, _ro("—"))

            # Pre-fill Expected Hours / Target / Efficiency using config values
            self._fill_derived_cells(
                t, first_r, lc, mc, bold,
                _uph_val, float(_mac_val), _wh_val,
                completed=completed,
                pass_u=pass_u,
                actual_work_hrs=work_hrs,
                lot_hours=float(agg.get("lot_hours", 0.0) or 0.0),
                operation_name=op,
                units_in=int(units),
            )
