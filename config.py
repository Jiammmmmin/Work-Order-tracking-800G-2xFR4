APP_NAME = "Work Order Tracking — 800G 2xFR4"
APP_VERSION = "1.0.0"
WINDOW_MIN_WIDTH = 1280
WINDOW_MIN_HEIGHT = 800
DB_SIMULATED_LATENCY = 1.5  # seconds

STYLESHEET = """
QMainWindow, QDialog {
    background-color: #F5F7FA;
}
QWidget {
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 13px;
    color: #212529;
}
QTabWidget::pane {
    border: 1px solid #DEE2E6;
    background: #FFFFFF;
    border-radius: 0px 4px 4px 4px;
}
QTabBar::tab {
    background: #E9ECEF;
    color: #495057;
    padding: 9px 22px;
    border: 1px solid #DEE2E6;
    border-bottom: none;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    margin-right: 3px;
}
QTabBar::tab:selected {
    background: #FFFFFF;
    color: #1565C0;
    font-weight: bold;
}
QTabBar::tab:hover:!selected {
    background: #D0D7DE;
}
QPushButton {
    background-color: #1565C0;
    color: white;
    padding: 7px 22px;
    border: none;
    border-radius: 4px;
    font-weight: bold;
    min-width: 80px;
}
QPushButton:hover  { background-color: #1976D2; }
QPushButton:pressed { background-color: #0D47A1; }
QPushButton:disabled { background-color: #B0BEC5; color: #ECEFF1; }
QComboBox {
    padding: 6px 10px;
    border: 1px solid #DEE2E6;
    border-radius: 4px;
    background: #FFFFFF;
    min-width: 130px;
}
QComboBox:hover { border-color: #1565C0; }
QComboBox::drop-down { border: none; width: 20px; }
QComboBox::down-arrow { width: 12px; height: 12px; }
QDateEdit {
    padding: 6px 10px;
    border: 1px solid #DEE2E6;
    border-radius: 4px;
    background: #FFFFFF;
    min-width: 120px;
}
QDateEdit:hover { border-color: #1565C0; }
QPlainTextEdit, QTextEdit {
    border: 1px solid #DEE2E6;
    border-radius: 4px;
    background: #FFFFFF;
    padding: 4px;
}
QPlainTextEdit:focus, QTextEdit:focus { border-color: #1565C0; }
QTableWidget {
    border: 1px solid #DEE2E6;
    gridline-color: #F0F0F0;
    alternate-background-color: #F8F9FA;
    selection-background-color: #BBDEFB;
    selection-color: #212529;
}
QHeaderView::section {
    background-color: #E9ECEF;
    color: #495057;
    padding: 7px 6px;
    border: none;
    border-right: 1px solid #DEE2E6;
    border-bottom: 1px solid #DEE2E6;
    font-weight: bold;
}
QProgressBar {
    border: none;
    border-radius: 4px;
    background: #E9ECEF;
    height: 10px;
    text-align: center;
}
QProgressBar::chunk {
    background: #1565C0;
    border-radius: 4px;
}
QStatusBar {
    background: #F8F9FA;
    color: #6C757D;
    border-top: 1px solid #DEE2E6;
    padding: 2px 8px;
}
QLabel#sectionTitle {
    font-size: 15px;
    font-weight: bold;
    color: #1565C0;
}
"""
