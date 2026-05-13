from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional




@dataclass
class QueryParams:
    product_type: str
    query_type: str
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    wo_list: Optional[List[str]] = None


@dataclass
class WorkOrderData:
    wo_number: str
    product_type: str
    yield_pct: float
    start_date: date
    end_date: date
    status: str
    station: str
    total_qty: int
    pass_qty: int             # INVQTY
    planned_qty: int = 0
    schedule_date: Optional[date] = None
    maktx: str = ""
    wip_qty: int = 0
    inv_qty: int = 0
    repair_qty: int = 0
    scrap_qty: int = 0
    finished: str = "N"

    @property
    def fail_qty(self) -> int:
        return self.scrap_qty + self.repair_qty


@dataclass
class LotData:
    """One row from MES_WIP_LOT or MES_WIP_LOT_NONACTIVE."""
    lot: str
    wo: str
    pickupno: str          # parent/master lot; equals lot if not a split
    quantity: int          # current quantity in this lot
    status: str            # Wait / Run / Terminated / Finished …
    operation: str         # current (or last) operation
    bar: str = ""
    utray: str = ""


@dataclass
class LotOperationData:
    """Per-lot per-operation aggregated from DM.AOI_WIP_COMP_OPERATION + MES_WIP_COMP[_NONACTIVE]."""
    lot: str
    operation: str
    op_seq: float               # MIN(STARTSEQ)
    unit_count: int             # COUNT(DISTINCT WIP_COMP_SID)
    scrap_count: int            # SUM(SCRAP_FLAG = 'Y')
    repair_count: int           # SUM(REPAIR_FLAG = 'Y')
    start_time: Optional[datetime] = None   # MIN(BEGINTIME); None = not started
    end_time: Optional[datetime] = None     # MAX(ENDTIME);   None = in progress
    equipment: str = ""


@dataclass
class OperationData:
    """Per-WO per-operation aggregated history from DM.AOI_WIP_COMP_OPERATION."""
    wo: str
    operation: str
    op_seq: int
    unit_count: int
    scrap_count: int
    repair_count: int
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    equipment: str = ""


@dataclass
class FailCodeData:
    """Aggregated fail-code count per operation from DM.AOI_WIP_COMP_OPERATION."""
    operation: str
    fail_code: str
    fail_desc: str
    count: int


@dataclass
class StationData:
    station_id: str
    status: str
    current_wo: str
    product_type: str
    throughput_per_hr: int
    uptime_pct: float


@dataclass
class QueryResult:
    work_orders: List[WorkOrderData] = field(default_factory=list)
    operation_history: List[OperationData] = field(default_factory=list)
    lot_tracking: List[LotData] = field(default_factory=list)
    lot_operations: List[LotOperationData] = field(default_factory=list)
    fail_codes: List["FailCodeData"] = field(default_factory=list)
    # Yield aggregates
    avg_yield: float = 0.0
    min_yield: float = 0.0
    max_yield: float = 0.0
    total_wos: int = 0
    # Production totals
    total_planned_qty: int = 0
    total_pass_qty: int = 0
    total_scrap_qty: int = 0
    total_wip_qty: int = 0
    total_inv_qty: int = 0
    total_repair_qty: int = 0
    query_params: Optional[QueryParams] = None
