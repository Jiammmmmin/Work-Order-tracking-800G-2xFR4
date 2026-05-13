from PyQt6.QtCore import QThread, pyqtSignal

from .database import DummyDatabase
from .data_models import QueryParams, QueryResult


def _make_summary_db():
    """Return MesDatabase if reachable, otherwise DummyDatabase."""
    try:
        from .mes import MesDatabase
        db = MesDatabase()
        if db.ping():
            return db, "live"
    except Exception:
        pass
    return DummyDatabase(), "dummy"


class QueryWorker(QThread):
    result_ready = pyqtSignal(object)   # QueryResult
    error_occurred = pyqtSignal(str)
    source_info = pyqtSignal(str)       # "live" or "dummy"

    def __init__(self, params: QueryParams, parent=None):
        super().__init__(parent)
        self._params = params

    def run(self):
        try:
            db, source = _make_summary_db()
            self.source_info.emit(source)
            result = db.query_summary(self._params)
            self.result_ready.emit(result)
        except Exception as exc:
            self.error_occurred.emit(str(exc))


class ScheduleWorker(QThread):
    result_ready = pyqtSignal(list)
    error_occurred = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._db = DummyDatabase()

    def run(self):
        try:
            data = self._db.query_schedule()
            self.result_ready.emit(data)
        except Exception as exc:
            self.error_occurred.emit(str(exc))


class StationWorker(QThread):
    result_ready = pyqtSignal(list)
    error_occurred = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._db = DummyDatabase()

    def run(self):
        try:
            data = self._db.query_station_info()
            self.result_ready.emit(data)
        except Exception as exc:
            self.error_occurred.emit(str(exc))
