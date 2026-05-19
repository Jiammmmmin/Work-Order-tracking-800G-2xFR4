import random
import time
from datetime import date, datetime, timedelta
from typing import List, Optional

from .data_models import WorkOrderData, LotData, LotOperationData, OperationData, FailCodeData, StationData, QueryParams, QueryResult
from ..utils.constants import STATIONS, WO_STATUSES, PRODUCT_TYPES

_BASE_THROUGHPUT = {"ST-01": 120, "ST-02": 95, "ST-03": 110, "ST-04": 105, "ST-05": 130, "ST-06": 88}

# Process operations per product type in route order (mirrors real MES routes)
_OPERATIONS = {
    "BOSA": [
        "StartRuncard", "RX_DB", "RX_Baking", "FSI_DB", "FSI_Baking",
        "TX_COS_DB", "Die_Visual_Inspection", "Dimension_Test",
        "TX_COS_Baking", "COB_WB", "Die_Wire_Inspection",
        "TX_Lens_Coupling", "COB_Black_Glue_Fixing",
        "COB_Black_Glue_Baking", "COB_Visual_Inspection",
    ],
    "COS": [
        "StartRuncard", "COS_Eutectic", "COS_Plasma", "COS_Wire_Bonding",
        "COS_Fixture_Assembly", "COS_Fixture_Disassembly_Unloading",
        "COS_Burn-in_Before", "COS_Burn-in_Test", "COS_Burn-in_After",
        "COS_Alignment", "COS_UV_Cure", "COS_Final_Test",
        "COS_OQC", "INVT_Hoop", "COS_Inspection",
    ],
    "TTX": [
        "StartRuncard", "TTX_Assembly", "TTX_Baking",
        "TTX_Burn-in", "TTX_Optical_Test", "TTX_Electrical_Test",
        "TTX_Final_Test", "TTX_Inspection",
    ],
}

_EQUIPMENT = {
    "COS_Eutectic": "COSEutectic1", "COS_Wire_Bonding": "COSWireBonding1",
    "COS_Burn-in_Before": "COSBurnin1", "COS_Burn-in_Test": "COSBurnin2",
    "COS_Burn-in_After": "COSBurnin2",
    "COS_Fixture_Disassembly_Unloading": "COSFixture1",
    "COS_OQC": "COSOQC1", "INVT_Hoop": "COSInvt1",
    "RX_DB": "DBBonder1", "COB_WB": "WireBonder1",
}


class DummyDatabase:
    def query_summary(self, params: QueryParams) -> QueryResult:
        time.sleep(1.5)

        if params.query_type == "Date":
            wos = self._generate_by_date_range(params)
        else:
            wos = self._generate_by_wo_list(params)

        if not wos:
            return QueryResult(query_params=params)

        op_hist              = self._generate_operation_history(wos, params.product_type)
        lot_tracking, lot_ops = self._generate_lot_tracking(wos, op_hist, params.product_type)
        fail_codes            = self._generate_fail_codes(op_hist, params.product_type)
        yields    = [w.yield_pct for w in wos]
        total_qty = sum(w.total_qty for w in wos)
        total_inv = sum(w.inv_qty   for w in wos)
        avg_yield = round(sum(yields) / len(yields), 2) if yields else 0.0
        return QueryResult(
            work_orders=wos,
            operation_history=op_hist,
            lot_tracking=lot_tracking,
            lot_operations=lot_ops,
            fail_codes=fail_codes,
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
            query_params=params,
        )

    def query_schedule(self) -> List[WorkOrderData]:
        time.sleep(0.8)
        result = []
        for i in range(25):
            ptype = random.choice(PRODUCT_TYPES)
            result.append(self._make_wo(ptype, i))
        return result

    def query_station_info(self) -> List[StationData]:
        time.sleep(0.6)
        stations = []
        for sid in STATIONS:
            ptype = random.choice(PRODUCT_TYPES)
            uptime = round(random.uniform(88.0, 99.5), 1)
            throughput = _BASE_THROUGHPUT[sid] + random.randint(-10, 10)
            stations.append(StationData(
                station_id=sid,
                status=random.choice(["Running", "Running", "Running", "Idle", "Maintenance"]),
                current_wo=f"WO-{ptype}-{random.randint(2024000, 2024999):07d}",
                product_type=ptype,
                throughput_per_hr=throughput,
                uptime_pct=uptime,
            ))
        return stations

    def _generate_by_date_range(self, params: QueryParams) -> List[WorkOrderData]:
        count = random.randint(10, 22)
        return [self._make_wo(params.product_type, i) for i in range(count)]

    def _generate_by_wo_list(self, params: QueryParams) -> List[WorkOrderData]:
        return [self._make_wo(params.product_type, i, wo)
                for i, wo in enumerate(params.wo_list or [])]

    def _make_wo(self, product_type: str, idx: int, wo_num: str = None) -> WorkOrderData:
        if wo_num is None:
            wo_num = f"WO-{product_type}-{2024000 + idx:07d}"

        status     = random.choice(WO_STATUSES)
        total_qty  = random.choice([500, 1000, 2000, 2500, 5000])
        scrap_qty  = random.randint(0, max(1, total_qty // 40))
        repair_qty = random.randint(0, max(1, total_qty // 30))
        start      = date.today() - timedelta(days=random.randint(1, 90))
        end        = start + timedelta(days=random.randint(1, 14))

        if status == "Complete":
            inv_qty  = max(0, total_qty - scrap_qty - repair_qty)
            wip_qty  = 0
        else:
            processed = random.randint(total_qty // 4, total_qty)
            wip_qty   = max(0, processed - scrap_qty - repair_qty)
            inv_qty   = 0

        pass_qty = inv_qty

        if inv_qty > 0:
            yield_pct = round(inv_qty / total_qty * 100, 2) if total_qty else 0.0
        else:
            denom     = wip_qty + repair_qty + scrap_qty
            yield_pct = round(wip_qty / denom * 100, 2) if denom else 0.0

        return WorkOrderData(
            wo_number=wo_num,
            product_type=product_type,
            yield_pct=yield_pct,
            start_date=start,
            end_date=end,
            status=status,
            station=random.choice(STATIONS),
            total_qty=total_qty,
            pass_qty=pass_qty,
            planned_qty=total_qty,
            maktx=f"800G 2xFR4 {product_type} MODULE",
            wip_qty=wip_qty,
            inv_qty=inv_qty,
            repair_qty=repair_qty,
            scrap_qty=scrap_qty,
        )

    def _generate_lot_tracking(
        self,
        wos: list,
        op_hist: List[OperationData],
        product_type: str,
    ):
        """Generate dummy lot + lot-operation data mirroring DM.AOI_WIP_COMP_OPERATION."""
        from collections import defaultdict
        wo_ops: dict = defaultdict(list)
        for od in op_hist:
            wo_ops[od.wo].append(od)

        ops_template     = _OPERATIONS.get(product_type, ["Assembly", "Test", "Final"])
        _active_statuses = ["Wait", "Run"]
        _done_statuses   = ["Finished", "Terminated"]

        lots: List[LotData]          = []
        lot_ops: List[LotOperationData] = []

        for wo in wos:
            n_lots   = random.randint(2, 4)
            base_qty = max(1, wo.total_qty // n_lots)
            wo_od    = sorted(wo_ops.get(wo.wo_number, []), key=lambda x: x.op_seq)
            finished = wo.inv_qty > 0
            cur_op   = wo_od[-1].operation if wo_od else (ops_template[0] if ops_template else "")

            for lot_i in range(n_lots):
                lot_id = f"{wo.wo_number}-L{lot_i+1:02d}"
                qty    = (base_qty if lot_i < n_lots - 1
                          else max(1, wo.total_qty - base_qty * (n_lots - 1)))
                status = random.choice(_done_statuses if finished else _active_statuses)

                lots.append(LotData(
                    lot=lot_id,
                    wo=wo.wo_number,
                    pickupno=lot_id,
                    quantity=qty,
                    status=status,
                    operation=cur_op,
                ))

                # Per-lot per-operation rows matching DM.AOI_WIP_COMP_OPERATION structure
                units = qty
                for od in wo_od:
                    scrap  = random.randint(0, max(0, units // 60))
                    repair = random.randint(0, max(0, units // 50))
                    in_prog = (od.end_time is None)

                    lot_ops.append(LotOperationData(
                        lot=lot_id,
                        operation=od.operation,
                        op_seq=float(od.op_seq),
                        unit_count=units,
                        scrap_count=scrap,
                        repair_count=repair,
                        start_time=od.start_time,
                        end_time=None if in_prog else od.end_time,
                        equipment=od.equipment,
                    ))
                    units = max(0, units - scrap - repair)

        return lots, lot_ops

    def _generate_operation_history(self, wos: list, product_type: str) -> List[OperationData]:
        ops = _OPERATIONS.get(product_type, ["Assembly", "Test", "Final"])
        result = []
        for wo in wos:
            # Simulate how far through the route this WO has progressed
            is_done      = wo.inv_qty > 0
            ops_done_cnt = len(ops) if is_done else random.randint(1, len(ops))
            t = datetime(
                wo.start_date.year, wo.start_date.month, wo.start_date.day,
                random.randint(7, 9), random.randint(0, 59)
            )
            remaining = wo.total_qty
            for seq, op in enumerate(ops):
                if seq >= ops_done_cnt:
                    break
                is_last = (seq == ops_done_cnt - 1)
                duration_h = random.uniform(0.5, 8.0)
                start_t    = t
                end_t: Optional[datetime] = None if (is_last and not is_done) else (t + timedelta(hours=duration_h))

                scrap  = random.randint(0, max(0, remaining // 50))
                repair = random.randint(0, max(0, remaining // 40))
                units  = max(0, remaining - scrap - repair)
                remaining = units

                result.append(OperationData(
                    wo=wo.wo_number,
                    operation=op,
                    op_seq=seq,
                    unit_count=units,
                    scrap_count=scrap,
                    repair_count=repair,
                    start_time=start_t,
                    end_time=end_t,
                    equipment=_EQUIPMENT.get(op, ""),
                ))
                if end_t:
                    t = end_t + timedelta(minutes=random.randint(5, 60))
        return result

    def _generate_fail_codes(
        self, op_hist: List[OperationData], product_type: str
    ) -> List[FailCodeData]:
        _FAIL_POOL = {
            "BOSA": [
                ("FC001", "Die crack"),
                ("FC002", "Wire bond open"),
                ("FC003", "Misalignment"),
                ("FC004", "Contamination"),
                ("FC005", "Delamination"),
            ],
            "COS": [
                ("FC010", "Eutectic void"),
                ("FC011", "Bond wire short"),
                ("FC012", "Burn-in fail"),
                ("FC013", "Alignment error"),
                ("FC014", "UV cure incomplete"),
            ],
            "TTX": [
                ("FC020", "Optical power low"),
                ("FC021", "ER fail"),
                ("FC022", "TDECQ fail"),
                ("FC023", "Assembly defect"),
                ("FC024", "Burn-in timeout"),
            ],
        }
        pool = _FAIL_POOL.get(product_type, _FAIL_POOL["BOSA"])
        from collections import defaultdict
        counts: dict = defaultdict(lambda: defaultdict(int))
        for od in op_hist:
            total_fail = od.scrap_count + od.repair_count
            if total_fail == 0:
                continue
            for _ in range(total_fail):
                code, desc = random.choice(pool)
                counts[od.operation][(code, desc)] += 1
        result = []
        for op, fc_map in counts.items():
            for (code, desc), cnt in fc_map.items():
                result.append(FailCodeData(
                    operation=op, fail_code=code, fail_desc=desc, count=cnt,
                ))
        return result
