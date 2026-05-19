"""Built-in 2xFR4 station targets from planning sheets (Target UPH, # machines, 7h shift).

Keys must match MES / app operation names (route order). Excel in data/station_config.xlsx
can still override if you remove an entry here; merge applies these after MES equipment counts.
"""

from __future__ import annotations

from typing import Dict, TypedDict


class _Row(TypedDict):
    target_uph: float
    machines: int
    work_hours: float


WH: float = 7.0

# COS — from 2xFR4 COS station table (MES names from AOI route)
BUILTIN_COS: Dict[str, _Row] = {
    "StartRuncard":        {"target_uph": 10.0, "machines": 1, "work_hours": WH},
    "COS_Eutectic":        {"target_uph": 41.0, "machines": 6, "work_hours": WH},
    "COS_Plasma":          {"target_uph": 596.0, "machines": 1, "work_hours": WH},
    "COS_Wire_Bonding":    {"target_uph": 236.0, "machines": 1, "work_hours": WH},
    "COS_Fixture_Assembly": {"target_uph": 180.0, "machines": 1, "work_hours": WH},
    # Fixture off-load (MES name); same UPH band as COS_Fixture_Assembly
    "COS_Fixture_Disassembly_Unloading": {"target_uph": 180.0, "machines": 1, "work_hours": WH},
    "COS_Burn-in_Before":  {"target_uph": 76.0, "machines": 3, "work_hours": WH},
    "COS_Burn-in_Test":    {"target_uph": 76.0, "machines": 3, "work_hours": WH},
    # Post-burn soak (MES name); same line rate as COS burn-in stations
    "COS_Burn-in_After":   {"target_uph": 76.0, "machines": 3, "work_hours": WH},
    "COS_Alignment":       {"target_uph": 10.0, "machines": 1, "work_hours": WH},
    "COS_UV_Cure":         {"target_uph": 34.0, "machines": 4, "work_hours": WH},
    "COS_Final_Test":      {"target_uph": 60.0, "machines": 1, "work_hours": WH},
    # OQC / inventory hoop — planning Target UPH 60 each (must be in BUILTIN so Excel rows get overwritten)
    "COS_OQC":             {"target_uph": 60.0, "machines": 1, "work_hours": WH},
    "INVT_Hoop":           {"target_uph": 60.0, "machines": 1, "work_hours": WH},
    "INVT_HOOP":           {"target_uph": 60.0, "machines": 1, "work_hours": WH},
    # OQC / final visual
    "COS_Inspection":      {"target_uph": 60.0, "machines": 1, "work_hours": WH},
    "COS_Visual_Inspection": {"target_uph": 60.0, "machines": 1, "work_hours": WH},
    "COS-Visual Inspection": {"target_uph": 60.0, "machines": 1, "work_hours": WH},
}

# BOSA route — COB + BOS assembly rows from 2xFR4 COB / BOS draft sheets
BUILTIN_BOSA: Dict[str, _Row] = {
    "StartRuncard":              {"target_uph": 10.0, "machines": 1, "work_hours": WH},
    "RX_DB":                     {"target_uph": 16.0, "machines": 2, "work_hours": WH},
    "RX_Baking":                 {"target_uph": 248.0, "machines": 1, "work_hours": WH},
    "FSI_DB":                    {"target_uph": 51.0, "machines": 2, "work_hours": WH},
    "FSI_Baking":                {"target_uph": 248.0, "machines": 1, "work_hours": WH},
    "TX_COS_DB":                 {"target_uph": 23.0, "machines": 2, "work_hours": WH},
    "Die_Visual_Inspection":     {"target_uph": 60.0, "machines": 1, "work_hours": WH},
    "Dimension_Test":            {"target_uph": 51.0, "machines": 1, "work_hours": WH},
    "TX_COS_Baking":             {"target_uph": 248.0, "machines": 1, "work_hours": WH},
    "COB_WB":                    {"target_uph": 32.0, "machines": 1, "work_hours": WH},
    "Die_Wire_Inspection":       {"target_uph": 180.0, "machines": 1, "work_hours": WH},
    "TX_Lens_Coupling":          {"target_uph": 4.0, "machines": 7, "work_hours": WH},
    "COB_Black_Glue_Fixing":     {"target_uph": 40.0, "machines": 1, "work_hours": WH},
    "COB_Black_Glue_Baking":     {"target_uph": 248.0, "machines": 1, "work_hours": WH},
    "COB_Visual_Inspection":     {"target_uph": 60.0, "machines": 1, "work_hours": WH},
    # BOS Assembly block (when MES uses these operation names)
    "Housing_Assembly":          {"target_uph": 60.0, "machines": 1, "work_hours": WH},
    "RX_FA_Coupling":            {"target_uph": 6.0, "machines": 6, "work_hours": WH},
    "TX_FA_Coupling":            {"target_uph": 6.0, "machines": 6, "work_hours": WH},
    "FA_Black_Glue_Fixing":      {"target_uph": 19.0, "machines": 2, "work_hours": WH},
    "BOSA_Baking_1":             {"target_uph": 22.0, "machines": 1, "work_hours": WH},
    "FA_Visual_Inspection":      {"target_uph": 60.0, "machines": 1, "work_hours": WH},
    "LE_Cover_Assembly":         {"target_uph": 60.0, "machines": 1, "work_hours": WH},
    "LE_Cover_Visual_Inspection": {"target_uph": 60.0, "machines": 1, "work_hours": WH},
    "TRX_Cover_Assembly":        {"target_uph": 52.0, "machines": 1, "work_hours": WH},
    "Baking_TC":                 {"target_uph": 22.0, "machines": 1, "work_hours": WH},
    "Module_Visual_Inspection":  {"target_uph": 60.0, "machines": 1, "work_hours": WH},
}

# TTX — map planning TTX table to dummy-route op names used in app / sample DB
BUILTIN_TTX: Dict[str, _Row] = {
    "StartRuncard":       {"target_uph": 10.0, "machines": 1, "work_hours": WH},
    "TTX_Assembly":       {"target_uph": 25.0, "machines": 3, "work_hours": WH},   # FW Writing
    "TTX_Baking":         {"target_uph": 12.0, "machines": 1, "work_hours": WH},   # DDMI
    "TTX_Burn-in":        {"target_uph": 11.0, "machines": 2, "work_hours": WH},
    "TTX_Optical_Test":   {"target_uph": 16.0, "machines": 3, "work_hours": WH},   # 3T BER
    "TTX_Electrical_Test": {"target_uph": 12.0, "machines": 2, "work_hours": WH}, # TC BER
    "TTX_Final_Test":     {"target_uph": 11.0, "machines": 3, "work_hours": WH},
    "TTX_Inspection":     {"target_uph": 60.0, "machines": 1, "work_hours": WH},  # packing / final check band
}

BUILTIN_BY_PRODUCT: Dict[str, Dict[str, _Row]] = {
    "COS": BUILTIN_COS,
    "BOSA": BUILTIN_BOSA,
    "TTX": BUILTIN_TTX,
}
