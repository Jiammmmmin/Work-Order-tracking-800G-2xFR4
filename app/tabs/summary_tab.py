from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QSplitter,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont

from ..widgets.chart_widget import YieldChartWidget
from ..backend.data_models import QueryResult, WorkOrderData
from ..utils.constants import TARGET_YIELD


# ── KPI card ──────────────────────────────────────────────────────────────────

class _StatCard(QFrame):
    def __init__(self, title: str, accent: str = "#1565C0", parent=None):
        super().__init__(parent)
        self._accent = accent
        self.setObjectName("statCard")
        self.setStyleSheet(f"""
            QFrame#statCard {{
                background: #FFFFFF;
                border: 1px solid #DEE2E6;
                border-top: 3px solid {accent};
                border-radius: 6px;
                min-width: 115px;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(2)

        self._title_lbl = QLabel(title)
        self._title_lbl.setStyleSheet("color: #6C757D; font-size: 10px; font-weight: bold;")
        self._title_lbl.setWordWrap(True)
        layout.addWidget(self._title_lbl)

        self._value_lbl = QLabel("—")
        self._value_lbl.setStyleSheet(f"color: {accent}; font-size: 19px; font-weight: bold;")
        layout.addWidget(self._value_lbl)

        self._sub_lbl = QLabel("")
        self._sub_lbl.setStyleSheet("color: #9E9E9E; font-size: 9px;")
        layout.addWidget(self._sub_lbl)

    def set_value(self, value: str, sub: str = ""):
        self._value_lbl.setText(value)
        self._sub_lbl.setText(sub)
        self._sub_lbl.setVisible(bool(sub))

    def reset(self):
        self._value_lbl.setText("—")
        self._sub_lbl.setText("")
        self._sub_lbl.setVisible(False)


# ── KPI row ───────────────────────────────────────────────────────────────────

class _KpiBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self._wos      = _StatCard("Total WOs",      "#1565C0")
        self._planned  = _StatCard("WO Qty",          "#1565C0")
        self._inv      = _StatCard("Completed (INV)", "#2E7D32")
        self._wip      = _StatCard("In WIP",          "#E65100")
        self._repair   = _StatCard("In Repair",       "#F57F17")
        self._scrap    = _StatCard("Scrap Qty",       "#B71C1C")
        self._notstart = _StatCard("Not Started",     "#757575")
        self._avg      = _StatCard("Avg Yield",       "#1565C0")

        for card in (self._wos, self._planned, self._inv, self._wip,
                     self._repair, self._scrap, self._notstart, self._avg):
            layout.addWidget(card)
        layout.addStretch()

    def update(self, r: QueryResult):
        not_started = max(0, r.total_planned_qty
                         - r.total_wip_qty
                         - r.total_inv_qty
                         - r.total_repair_qty
                         - r.total_scrap_qty)
        self._wos.set_value(str(r.total_wos))
        self._planned.set_value(
            f"{r.total_planned_qty:,}",
            f"= {r.total_inv_qty:,} + {r.total_wip_qty:,} + {r.total_repair_qty:,} + {r.total_scrap_qty:,} + {not_started:,}",
        )
        self._inv.set_value(f"{r.total_inv_qty:,}")
        self._wip.set_value(f"{r.total_wip_qty:,}")
        self._repair.set_value(str(r.total_repair_qty))
        self._scrap.set_value(str(r.total_scrap_qty))
        self._notstart.set_value(str(not_started))
        self._avg.set_value(
            f"{r.avg_yield:.1f}%",
            f"min {r.min_yield:.1f}%  max {r.max_yield:.1f}%",
        )

    def reset(self):
        for card in (self._wos, self._planned, self._inv, self._wip,
                     self._repair, self._scrap, self._notstart, self._avg):
            card.reset()


# ── WO detail table ───────────────────────────────────────────────────────────

_HEADERS = [
    "WO Number", "Type", "Description", "Status",
    "WO Qty", "Pass (INV)", "Fail", "Scrap", "Repair",
    "In WIP", "Yield %",
    "Start Date", "Schedule Date", "Finished",
]

_STATUS_COLOR = {
    "Created":  "#1565C0",
    "Released": "#2E7D32",
    "Finished": "#424242",
    "Closed":   "#424242",
    "On Hold":  "#E65100",
}


def _yield_color(y: float) -> QColor:
    if y >= TARGET_YIELD:
        return QColor("#E8F5E9")
    if y >= 80.0:
        return QColor("#FFF3E0")
    return QColor("#FFEBEE")


def _yield_fg(y: float) -> QColor:
    if y >= TARGET_YIELD:
        return QColor("#2E7D32")
    if y >= 80.0:
        return QColor("#E65100")
    return QColor("#C62828")


class _WoTable(QTableWidget):
    def __init__(self, parent=None):
        super().__init__(0, len(_HEADERS), parent)
        self.setHorizontalHeaderLabels(_HEADERS)
        self.setAlternatingRowColors(True)
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.setSortingEnabled(True)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setStretchLastSection(False)
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.setMinimumHeight(160)

    def populate(self, work_orders: list[WorkOrderData]):
        self.setSortingEnabled(False)
        self.setRowCount(0)
        bold = QFont()
        bold.setBold(True)

        for wo in work_orders:
            r = self.rowCount()
            self.insertRow(r)
            fail = wo.scrap_qty + wo.repair_qty
            cells = [
                (wo.wo_number,                          None,                                           None),
                (wo.product_type,                       None,                                           None),
                (wo.maktx or "—",                       None,                                           None),
                (wo.status or "—",                      QColor(_STATUS_COLOR.get(wo.status, "#424242")), None),
                (f"{wo.total_qty:,}",                   None,                                           None),
                (f"{wo.pass_qty:,}",                    QColor("#2E7D32"),                              None),   # pass = INV
                (str(fail),                             QColor("#C62828") if fail else None,            None),
                (str(wo.scrap_qty),                     QColor("#B71C1C") if wo.scrap_qty else None,    None),
                (str(wo.repair_qty),                    QColor("#E65100") if wo.repair_qty else None,   None),
                (f"{wo.wip_qty:,}",                     None,                                           None),
                (f"{wo.yield_pct:.2f}%",                _yield_fg(wo.yield_pct),                        _yield_color(wo.yield_pct)),
                (str(wo.start_date),                    None,                                           None),
                (str(wo.schedule_date or wo.end_date),  None,                                           None),
                (wo.finished or "N",                    None,                                           None),
            ]
            for c, (text, fg, bg) in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 0:
                    item.setFont(bold)
                if fg:
                    item.setForeground(fg)
                if bg:
                    item.setBackground(bg)
                self.setItem(r, c, item)

        self.setSortingEnabled(True)
        self.resizeColumnsToContents()
        self.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)

    def clear_rows(self):
        self.setRowCount(0)


# ── Summary Tab ───────────────────────────────────────────────────────────────

class SummaryTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(12)

        # KPI bar
        self.kpi_bar = _KpiBar()
        layout.addWidget(self.kpi_bar)

        # Splitter: chart (top) + WO table (bottom)
        splitter = QSplitter(Qt.Orientation.Vertical)

        self.chart = YieldChartWidget()
        splitter.addWidget(self.chart)

        self.wo_table = _WoTable()
        splitter.addWidget(self.wo_table)

        splitter.setSizes([340, 220])
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, stretch=1)

    # ── Public API ────────────────────────────────────────────────────────────

    def update_result(self, result: QueryResult):
        self.kpi_bar.update(result)
        self.chart.update_chart(result)
        self.wo_table.populate(result.work_orders)

    def reset(self):
        self.kpi_bar.reset()
        self.wo_table.clear_rows()
        self.chart._draw_placeholder()
