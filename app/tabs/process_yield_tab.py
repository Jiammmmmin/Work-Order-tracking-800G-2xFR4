from collections import defaultdict

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QSplitter, QScrollArea,
)

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont

from ..widgets.chart_widget import YieldChartWidget, FailModeChartWidget
from ..backend.data_models import QueryResult, WorkOrderData, OperationData, LotOperationData

from ..utils.constants import TARGET_YIELD, PRODUCT_TYPES

_SUMMARY_HEADERS = [
    "Type", "WO Count", "Total Qty", "Completed (INV)",
    "In WIP", "Scrap", "Repair", "Avg Yield %", "Min Yield %", "Max Yield %",
]

_PROC_HEADERS = ["Process", "N In", "N Out", "Fail", "WIP", "Yield %"]


def _yield_fg(y: float) -> QColor:
    if y >= TARGET_YIELD: return QColor("#2E7D32")
    if y >= 80.0:         return QColor("#E65100")
    return QColor("#C62828")


def _yield_bg(y: float) -> QColor:
    if y >= TARGET_YIELD: return QColor("#E8F5E9")
    if y >= 80.0:         return QColor("#FFF3E0")
    return QColor("#FFEBEE")


def _ro(text, fg=None, bg=None, bold=False, align=Qt.AlignmentFlag.AlignCenter):
    item = QTableWidgetItem(text)
    item.setTextAlignment(align)
    item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
    if fg:   item.setForeground(fg if isinstance(fg, QColor) else QColor(fg))
    if bg:   item.setBackground(bg if isinstance(bg, QColor) else QColor(bg))
    if bold:
        f = QFont(); f.setBold(True); item.setFont(f)
    return item


class ProcessYieldTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 12, 0, 0)
        outer.setSpacing(8)

        self._placeholder = QLabel("Run a query to view process yield analytics.")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setStyleSheet("color: #9E9E9E; font-size: 13px;")
        outer.addWidget(self._placeholder)

        # Scroll area wraps everything below the placeholder
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._scroll.hide()
        outer.addWidget(self._scroll, stretch=1)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        self._scroll.setWidget(container)

        # ── Top: per-type summary table ───────────────────────────────────────
        self._summary_table = QTableWidget(0, len(_SUMMARY_HEADERS))
        self._summary_table.setHorizontalHeaderLabels(_SUMMARY_HEADERS)
        self._summary_table.setAlternatingRowColors(True)
        self._summary_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._summary_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._summary_table.verticalHeader().setVisible(False)
        self._summary_table.horizontalHeader().setStretchLastSection(True)
        self._summary_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._summary_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        layout.addWidget(self._summary_table)

        # ── WO yield chart ────────────────────────────────────────────────────
        self.chart = YieldChartWidget()
        self.chart.setMinimumHeight(340)
        layout.addWidget(self.chart)

        # ── Per-process flat table ────────────────────────────────────────────
        self._proc_label = QLabel("Process Summary")
        self._proc_label.setStyleSheet("font-weight: bold; font-size: 12px; padding: 4px 0;")
        layout.addWidget(self._proc_label)

        self._proc_table = QTableWidget(0, len(_PROC_HEADERS))
        self._proc_table.setHorizontalHeaderLabels(_PROC_HEADERS)
        self._proc_table.setAlternatingRowColors(True)
        self._proc_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._proc_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._proc_table.verticalHeader().setVisible(False)
        self._proc_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._proc_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._proc_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._proc_table)

        # ── Fail mode pareto chart ────────────────────────────────────────────
        self._fail_label = QLabel("Fail Mode Pareto")
        self._fail_label.setStyleSheet("font-weight: bold; font-size: 12px; padding: 4px 0;")
        layout.addWidget(self._fail_label)

        self._fail_chart = FailModeChartWidget()
        self._fail_chart.setMinimumHeight(500)
        layout.addWidget(self._fail_chart)

    # ── Public API ────────────────────────────────────────────────────────────

    def update_result(self, result: QueryResult):
        self._placeholder.hide()
        self._scroll.show()
        params     = result.query_params
        start_date = getattr(params, "start_date", None) if params else None
        end_date   = getattr(params, "end_date",   None) if params else None
        self._populate_summary(result.work_orders)
        self.chart.update_chart(result)
        self._populate_process_tables(result, start_date, end_date)
        self._fail_chart.update_chart(result.fail_codes)
        self._fit_height(self._summary_table)

    def reset(self):
        self._scroll.hide()
        self._summary_table.setRowCount(0)
        self._proc_table.setRowCount(0)
        self.chart._draw_placeholder()
        self._fail_chart._draw_placeholder()
        self._placeholder.show()

    # ── Private ───────────────────────────────────────────────────────────────

    def _populate_summary(self, work_orders: list[WorkOrderData]):
        groups: dict[str, list[WorkOrderData]] = {}
        for wo in work_orders:
            groups.setdefault(wo.product_type, []).append(wo)

        self._summary_table.setRowCount(0)

        for ptype in PRODUCT_TYPES:
            wos = groups.get(ptype)
            if not wos:
                continue
            total_qty  = sum(w.total_qty  for w in wos)
            inv_qty    = sum(w.inv_qty    for w in wos)
            wip_qty    = sum(w.wip_qty    for w in wos)
            scrap_qty  = sum(w.scrap_qty  for w in wos)
            repair_qty = sum(w.repair_qty for w in wos)
            yields     = [w.yield_pct for w in wos]
            total_pass = sum(w.pass_qty   for w in wos)
            avg_y = round(total_pass / total_qty * 100, 2) if total_qty else 0.0
            min_y = round(min(yields), 2)
            max_y = round(max(yields), 2)

            r = self._summary_table.rowCount()
            self._summary_table.insertRow(r)
            cells = [
                (ptype,              None,             None),
                (str(len(wos)),      None,             None),
                (f"{total_qty:,}",   None,             None),
                (f"{inv_qty:,}",     QColor("#2E7D32"), None),
                (f"{wip_qty:,}",     None,             None),
                (str(scrap_qty),     QColor("#B71C1C") if scrap_qty else None, None),
                (str(repair_qty),    QColor("#E65100") if repair_qty else None, None),
                (f"{avg_y:.1f}%",    _yield_fg(avg_y), _yield_bg(avg_y)),
                (f"{min_y:.1f}%",    _yield_fg(min_y), None),
                (f"{max_y:.1f}%",    _yield_fg(max_y), None),
            ]
            for c, (text, fg, bg) in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if fg: item.setForeground(fg)
                if bg: item.setBackground(bg)
                self._summary_table.setItem(r, c, item)

        self._summary_table.resizeColumnsToContents()
        self._summary_table.horizontalHeader().setStretchLastSection(True)

    def _populate_process_tables(self, result: QueryResult, start_date=None, end_date=None):
        op_history  = result.operation_history
        lot_ops     = result.lot_operations

        def _in_range(t_val):
            if t_val is None or start_date is None or end_date is None:
                return t_val is not None
            d = t_val.date() if hasattr(t_val, "date") else t_val
            return start_date <= d <= end_date

        # ── Aggregate per-operation — only entries with activity in date range ─
        agg: dict[str, dict] = {}
        seq_map: dict[str, int] = {}
        for od in op_history:
            if not (_in_range(od.start_time) or _in_range(od.end_time)):
                continue
            a = agg.setdefault(od.operation, {"n_in": 0, "scrap": 0, "repair": 0})
            a["n_in"]   += od.unit_count
            a["scrap"]  += od.scrap_count
            a["repair"] += od.repair_count
            if od.operation not in seq_map or od.op_seq < seq_map[od.operation]:
                seq_map[od.operation] = od.op_seq

        # WIP = lot_ops started but not yet completed (irrespective of date range)
        wip_by_op: dict[str, int] = defaultdict(int)
        for lo in lot_ops:
            if lo.start_time is not None and lo.end_time is None:
                wip_by_op[lo.operation] += lo.unit_count

        # Sort by route order
        ops_ordered = sorted(agg.keys(), key=lambda op: seq_map.get(op, 9999))

        # ── Process flat table ────────────────────────────────────────────────
        pt = self._proc_table
        pt.setRowCount(0)

        for op in ops_ordered:
            a     = agg[op]
            n_in  = a["n_in"]
            fail  = a["scrap"] + a["repair"]
            n_out = max(0, n_in - fail)
            wip   = wip_by_op.get(op, 0)
            yld   = round(n_out / n_in * 100, 1) if n_in else 0.0

            r = pt.rowCount(); pt.insertRow(r); pt.setRowHeight(r, 24)
            pt.setItem(r, 0, _ro(op,                align=Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft))
            pt.setItem(r, 1, _ro(f"{n_in:,}"))
            pt.setItem(r, 2, _ro(f"{n_out:,}",      fg="#1B5E20", bg="#E8F5E9" if yld >= TARGET_YIELD else None, bold=True))
            pt.setItem(r, 3, _ro(f"{fail:,}",       fg="#B71C1C" if fail else None, bg="#FFEBEE" if fail else None))
            pt.setItem(r, 4, _ro(f"{wip:,}",        bg="#E3F2FD" if wip else None))
            yi = _ro(f"{yld:.1f}%", bold=True)
            yi.setForeground(_yield_fg(yld)); yi.setBackground(_yield_bg(yld))
            pt.setItem(r, 5, yi)

        pt.resizeColumnsToContents()
        pt.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._fit_height(pt)

    @staticmethod
    def _fit_height(t: QTableWidget):
        h = t.horizontalHeader().height() + sum(t.rowHeight(r) for r in range(t.rowCount())) + 4
        t.setFixedHeight(max(h, 60))
