from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QMessageBox, QSplitter,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont

from ..backend.worker import StationWorker
from ..backend.data_models import StationData, QueryResult
from ..widgets.loading_dialog import LoadingDialog
from ..utils import process_config

_STATION_HEADERS = ["Station ID", "Status", "Current WO", "Type", "Throughput/hr", "Uptime %"]
_CFG_HEADERS     = ["Process", "Target UPH", "# Machines", "Work Hours", "Equipment / Stations"]

_STATUS_COLOR = {
    "Running":     "#2E7D32",
    "Idle":        "#1565C0",
    "Maintenance": "#E65100",
}


class StationInfoTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker:  StationWorker | None = None
        self._loading: LoadingDialog | None = None
        self._product_type: str = "COS"
        self._build_ui()
        self._refresh()
        self._reload_cfg_table()

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        # ── Top bar ───────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        title = QLabel("Station Information")
        title.setObjectName("sectionTitle")
        hdr.addWidget(title)
        hdr.addStretch()
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setFixedWidth(90)
        self.refresh_btn.clicked.connect(self._refresh)
        hdr.addWidget(self.refresh_btn)
        layout.addLayout(hdr)

        splitter = QSplitter(Qt.Orientation.Vertical)

        # ── Station status table (top) ────────────────────────────────────────
        self._station_table = QTableWidget(0, len(_STATION_HEADERS))
        self._station_table.setHorizontalHeaderLabels(_STATION_HEADERS)
        self._station_table.setAlternatingRowColors(True)
        self._station_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._station_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._station_table.verticalHeader().setVisible(False)
        self._station_table.horizontalHeader().setStretchLastSection(True)
        splitter.addWidget(self._station_table)

        # ── Process config section (bottom) ───────────────────────────────────
        cfg_widget = QWidget()
        cfg_layout = QVBoxLayout(cfg_widget)
        cfg_layout.setContentsMargins(0, 8, 0, 0)
        cfg_layout.setSpacing(6)

        cfg_hdr = QHBoxLayout()
        self._cfg_title = QLabel(f"Process Config — {self._product_type}")
        bold = QFont(); bold.setBold(True); bold.setPointSize(10)
        self._cfg_title.setFont(bold)
        cfg_hdr.addWidget(self._cfg_title)
        cfg_hdr.addStretch()

        self._save_btn = QPushButton("Save to Excel")
        self._save_btn.setFixedWidth(110)
        self._save_btn.clicked.connect(self._save_config)
        cfg_hdr.addWidget(self._save_btn)
        cfg_layout.addLayout(cfg_hdr)

        self._cfg_table = QTableWidget(0, len(_CFG_HEADERS))
        self._cfg_table.setHorizontalHeaderLabels(_CFG_HEADERS)
        self._cfg_table.setAlternatingRowColors(True)
        self._cfg_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._cfg_table.verticalHeader().setVisible(False)
        hh = self._cfg_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self._cfg_table.setColumnWidth(1, 110)
        self._cfg_table.setColumnWidth(2, 100)
        self._cfg_table.setColumnWidth(3, 100)
        cfg_layout.addWidget(self._cfg_table)

        splitter.addWidget(cfg_widget)
        splitter.setSizes([300, 300])
        splitter.setChildrenCollapsible(False)
        layout.addWidget(splitter, stretch=1)

    # ── Public API ────────────────────────────────────────────────────────────

    def set_product_type(self, product_type: str) -> None:
        """Called when the type combo in the query panel changes."""
        self._product_type = product_type
        self._cfg_title.setText(f"Process Config — {product_type}")
        self._reload_cfg_table()

    def update_from_result(self, result: QueryResult) -> None:
        """Merge operations from the latest query result into the config table."""
        ptype = result.query_params.product_type if result.query_params else self._product_type
        if ptype != self._product_type:
            return

        # Collect operations in route order
        ops = list({od.operation for od in result.operation_history if od.operation})
        ops_ordered = sorted(ops, key=lambda op: min(
            (od.op_seq for od in result.operation_history if od.operation == op), default=0
        ))

        # Collect equipment per operation from operation_history and lot_operations
        equipment_by_op: dict[str, set[str]] = {}
        for od in result.operation_history:
            if od.operation and od.equipment:
                equipment_by_op.setdefault(od.operation, set()).add(od.equipment.strip())
        for lo in result.lot_operations:
            if lo.operation and lo.equipment:
                equipment_by_op.setdefault(lo.operation, set()).add(lo.equipment.strip())

        process_config.merge_operations(ptype, ops_ordered, equipment_by_op=equipment_by_op)
        self._reload_cfg_table()

    # ── Internal ──────────────────────────────────────────────────────────────

    def _reload_cfg_table(self):
        """Rebuild the config table from the in-memory cache."""
        t = self._cfg_table
        try:
            t.cellChanged.disconnect(self._on_cfg_cell_changed)
        except (RuntimeError, TypeError):
            pass
        t.setRowCount(0)

        cfg = process_config.all_ops(self._product_type)
        for op, vals in cfg.items():
            r = t.rowCount(); t.insertRow(r); t.setRowHeight(r, 26)

            # Col 0 — process name (read-only)
            name_item = QTableWidgetItem(op)
            name_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            t.setItem(r, 0, name_item)

            # Col 1 — Target UPH (editable)
            uph = vals.get("target_uph", process_config._DEFAULT_UPH)
            uph_str = "" if uph is None else str(int(uph) if uph == int(uph) else uph)
            t.setItem(r, 1, QTableWidgetItem(uph_str))
            t.item(r, 1).setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            # Col 2 — # Machines (editable)
            t.setItem(r, 2, QTableWidgetItem(str(vals.get("machines", process_config._DEFAULT_MACHINES))))
            t.item(r, 2).setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            # Col 3 — Work Hours (editable)
            wh = vals.get("work_hours", process_config._DEFAULT_WH)
            t.setItem(r, 3, QTableWidgetItem(str(int(wh) if wh == int(wh) else wh)))
            t.item(r, 3).setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            # Col 4 — Equipment / Stations (read-only)
            eq_set  = vals.get("equipment", set())
            eq_str  = ", ".join(sorted(eq_set)) if eq_set else ""
            eq_item = QTableWidgetItem(eq_str)
            eq_item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            eq_item.setForeground(QColor("#455A64"))
            t.setItem(r, 4, eq_item)

        t.cellChanged.connect(self._on_cfg_cell_changed)

    def _on_cfg_cell_changed(self, row: int, col: int):
        """Live-update the in-memory cache when user edits UPH, machines, or work hours."""
        if col not in (1, 2, 3):
            return
        t = self._cfg_table
        op_item = t.item(row, 0)
        if op_item is None:
            return
        op = op_item.text()

        def _fval(c):
            it = t.item(row, c)
            if it is None: return None
            txt = it.text().strip()
            try: return float(txt) if txt else None
            except ValueError: return None

        uph      = _fval(1)
        machines = int(_fval(2) or process_config._DEFAULT_MACHINES)
        work_hrs = _fval(3)
        if work_hrs is None:
            work_hrs = process_config._DEFAULT_WH

        existing = process_config._CONFIG.setdefault(self._product_type, {}).setdefault(op, {})
        existing["target_uph"] = uph if uph is not None else process_config._DEFAULT_UPH
        existing["machines"]   = machines
        existing["work_hours"] = work_hrs
        existing.setdefault("equipment", set())

    def _save_config(self):
        """Collect table values and save to Excel."""
        t = self._cfg_table
        ops_data: dict = {}
        for r in range(t.rowCount()):
            op_item = t.item(r, 0)
            if not op_item:
                continue
            op = op_item.text().strip()
            if not op:
                continue

            def _fval(col, r=r):
                it = t.item(r, col)
                if it is None: return None
                txt = it.text().strip()
                try: return float(txt) if txt else None
                except ValueError: return None

            uph      = _fval(1)
            machines = int(_fval(2) or process_config._DEFAULT_MACHINES)
            work_hrs = _fval(3)
            if work_hrs is None:
                work_hrs = process_config._DEFAULT_WH

            # Preserve equipment from in-memory cache
            cached   = process_config.get(self._product_type, op) or {}
            equipment = cached.get("equipment", set())

            ops_data[op] = {
                "target_uph": uph if uph is not None else process_config._DEFAULT_UPH,
                "machines":   machines,
                "work_hours": work_hrs,
                "equipment":  equipment,
            }

        try:
            process_config.save(self._product_type, ops_data)
            QMessageBox.information(
                self, "Saved",
                f"Process config for {self._product_type} saved to:\n"
                f"{process_config._EXCEL_PATH}",
            )
        except Exception as e:
            QMessageBox.critical(self, "Save Error", str(e))

    def _refresh(self):
        if self._worker and self._worker.isRunning():
            return
        self.refresh_btn.setEnabled(False)
        self._loading = LoadingDialog("Loading Station Info…", parent=self)
        self._loading.show()
        self._worker = StationWorker(parent=self)
        self._worker.result_ready.connect(self._populate_stations)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.start()

    def _populate_stations(self, stations: list[StationData]):
        if self._loading:
            self._loading.close()
        self.refresh_btn.setEnabled(True)
        t = self._station_table
        t.setRowCount(0)
        for st in stations:
            r = t.rowCount(); t.insertRow(r)
            cells = [st.station_id, st.status, st.current_wo,
                     st.product_type, str(st.throughput_per_hr), f"{st.uptime_pct:.1f}%"]
            for c, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                if c == 1:
                    item.setForeground(QColor(_STATUS_COLOR.get(st.status, "#757575")))
                t.setItem(r, c, item)
        t.resizeColumnsToContents()

    def _on_error(self, msg: str):
        if self._loading:
            self._loading.close()
        self.refresh_btn.setEnabled(True)
        QMessageBox.critical(self, "Error", msg)
