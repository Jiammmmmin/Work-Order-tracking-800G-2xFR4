from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel,
    QComboBox, QPushButton, QDateEdit, QPlainTextEdit,
    QStackedWidget, QFrame,
)
from PyQt6.QtCore import pyqtSignal, QDate

from ..utils.constants import PRODUCT_TYPES, QUERY_TYPES
from ..backend.data_models import QueryParams


class QueryPanel(QFrame):
    query_requested = pyqtSignal(object)  # QueryParams

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("queryPanel")
        self.setStyleSheet("""
            QFrame#queryPanel {
                background: #FFFFFF;
                border: 1px solid #DEE2E6;
                border-radius: 6px;
            }
        """)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(12)

        # ── Controls row ──────────────────────────────────────────────
        controls = QHBoxLayout()
        controls.setSpacing(10)

        controls.addWidget(QLabel("Type:"))
        self.type_combo = QComboBox()
        self.type_combo.addItems(PRODUCT_TYPES)
        controls.addWidget(self.type_combo)

        controls.addSpacing(16)

        controls.addWidget(QLabel("Query Type:"))
        self.query_type_combo = QComboBox()
        self.query_type_combo.addItems(QUERY_TYPES)
        self.query_type_combo.currentIndexChanged.connect(self._on_query_type_changed)
        controls.addWidget(self.query_type_combo)

        controls.addSpacing(16)

        self.query_btn = QPushButton("Query")
        self.query_btn.setFixedWidth(90)
        self.query_btn.clicked.connect(self._on_query_clicked)
        controls.addWidget(self.query_btn)

        controls.addStretch()
        root.addLayout(controls)

        # ── Dynamic input area (switches on Query Type) ───────────────
        self.stack = QStackedWidget()

        # Page 0 — Date range
        date_page = QWidget()
        date_row = QHBoxLayout(date_page)
        date_row.setContentsMargins(0, 0, 0, 0)
        date_row.setSpacing(10)
        date_row.addWidget(QLabel("Start Date:"))
        self.start_date = QDateEdit(QDate.currentDate().addDays(-30))
        self.start_date.setCalendarPopup(True)
        self.start_date.setDisplayFormat("yyyy-MM-dd")
        date_row.addWidget(self.start_date)
        date_row.addSpacing(16)
        date_row.addWidget(QLabel("End Date:"))
        self.end_date = QDateEdit(QDate.currentDate())
        self.end_date.setCalendarPopup(True)
        self.end_date.setDisplayFormat("yyyy-MM-dd")
        date_row.addWidget(self.end_date)
        date_row.addStretch()
        self.stack.addWidget(date_page)

        # Page 1 — WO list
        wo_page = QWidget()
        wo_col = QVBoxLayout(wo_page)
        wo_col.setContentsMargins(0, 0, 0, 0)
        wo_col.setSpacing(4)
        wo_col.addWidget(QLabel("Work Orders (one per line):"))
        self.wo_text = QPlainTextEdit()
        self.wo_text.setPlaceholderText("WO-COS-2024001\nWO-COS-2024002\n…")
        self.wo_text.setFixedHeight(72)
        wo_col.addWidget(self.wo_text)
        self.stack.addWidget(wo_page)

        root.addWidget(self.stack)

    def _on_query_type_changed(self, idx: int):
        self.stack.setCurrentIndex(idx)

    def _on_query_clicked(self):
        product_type = self.type_combo.currentText()
        query_type = self.query_type_combo.currentText()

        if query_type == "Date":
            params = QueryParams(
                product_type=product_type,
                query_type=query_type,
                start_date=self.start_date.date().toPyDate(),
                end_date=self.end_date.date().toPyDate(),
            )
        else:
            lines = self.wo_text.toPlainText().splitlines()
            wos = [ln.strip() for ln in lines if ln.strip()]
            if not wos:
                wos = [f"WO-{product_type}-{2024000 + i:07d}" for i in range(6)]
            params = QueryParams(
                product_type=product_type,
                query_type=query_type,
                wo_list=wos,
            )

        self.query_btn.setEnabled(False)
        self.query_requested.emit(params)

    def set_ready(self):
        self.query_btn.setEnabled(True)
