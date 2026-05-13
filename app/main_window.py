from PyQt6.QtWidgets import (
    QMainWindow, QTabWidget, QStatusBar, QLabel, QVBoxLayout, QWidget, QMessageBox,
)

import config
from .tabs.summary_tab import SummaryTab
from .tabs.wo_schedule_tab import WOScheduleTab
from .tabs.process_yield_tab import ProcessYieldTab
from .tabs.station_info_tab import StationInfoTab
from .widgets.query_panel import QueryPanel
from .widgets.loading_dialog import LoadingDialog
from .backend.worker import QueryWorker
from .backend.data_models import QueryParams, QueryResult
from .utils import process_config


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(config.APP_NAME)
        self.setMinimumSize(config.WINDOW_MIN_WIDTH, config.WINDOW_MIN_HEIGHT)
        self._worker: QueryWorker | None = None
        self._loading: LoadingDialog | None = None
        process_config.load()   # load saved process config on startup
        self._build_ui()

    def _build_ui(self):
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(16, 16, 16, 0)
        root_layout.setSpacing(10)

        # Shared query panel (above all tabs)
        self.query_panel = QueryPanel()
        self.query_panel.query_requested.connect(self._run_query)
        root_layout.addWidget(self.query_panel)

        # Tab widget
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)

        self._summary_tab       = SummaryTab()
        self._wo_schedule_tab   = WOScheduleTab()
        self._process_yield_tab = ProcessYieldTab()
        self._station_info_tab  = StationInfoTab()

        self.tabs.addTab(self._summary_tab,       "  Summary  ")
        self.tabs.addTab(self._wo_schedule_tab,   "  WO Schedule  ")
        self.tabs.addTab(self._process_yield_tab, "  Process Yield  ")
        self.tabs.addTab(self._station_info_tab,  "  Station Information  ")

        # Sync type combo → station tab
        self.query_panel.type_combo.currentTextChanged.connect(
            self._station_info_tab.set_product_type
        )
        # Set initial type
        self._station_info_tab.set_product_type(self.query_panel.type_combo.currentText())

        root_layout.addWidget(self.tabs, stretch=1)
        self.setCentralWidget(root)

        # Status bar
        status = QStatusBar()
        self._status_label = QLabel(f"v{config.APP_VERSION}  |  800G 2xFR4 Work Order Tracking")
        self._status_label.setContentsMargins(4, 0, 0, 0)
        status.addWidget(self._status_label)
        self.setStatusBar(status)

    # ── Query lifecycle ───────────────────────────────────────────────────────

    def _run_query(self, params: QueryParams):
        if self._worker and self._worker.isRunning():
            return

        self._summary_tab.reset()
        self._wo_schedule_tab.reset()
        self._process_yield_tab.reset()

        self._loading = LoadingDialog("Querying MES database…", parent=self)
        self._loading.show()

        self._worker = QueryWorker(params, parent=self)
        self._worker.result_ready.connect(self._on_result)
        self._worker.error_occurred.connect(self._on_error)
        self._worker.source_info.connect(self._on_source)
        self._worker.start()

    def _on_result(self, result: QueryResult):
        self._close_loading()
        self.query_panel.set_ready()
        self._summary_tab.update_result(result)
        self._station_info_tab.update_from_result(result)   # merge ops before WO schedule
        self._wo_schedule_tab.update_result(result)
        self._process_yield_tab.update_result(result)

    def _on_source(self, source: str):
        label = "MES (live)" if source == "live" else "Demo data (MES unreachable)"
        self._set_status(f"Data source: {label}")

    def _on_error(self, message: str):
        self._close_loading()
        self.query_panel.set_ready()
        QMessageBox.critical(self, "Query Error", message)

    def _close_loading(self):
        if self._loading:
            self._loading.close()
            self._loading = None

    def _set_status(self, message: str):
        self._status_label.setText(
            f"v{config.APP_VERSION}  |  800G 2xFR4 Work Order Tracking  |  {message}"
        )
