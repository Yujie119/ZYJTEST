"""Independent checks for the geometry audit, using cell/segment intersections."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
from audit_data import OUT, supercover


def brute_cells(x0, y0, x1, y1, shape):
    result = set()
    for r in range(shape[0]):
        for c in range(shape[1]):
            lower, upper = 0.0, 1.0
            for p0, p1, low, high in [(x0, x1, c, c + 1), (y0, y1, r, r + 1)]:
                if abs(p1 - p0) < 1e-14:
                    if p0 < low or p0 > high:
                        upper = -1
                        break
                else:
                    t1, t2 = sorted([(low - p0) / (p1 - p0), (high - p0) / (p1 - p0)])
                    lower, upper = max(lower, t1), min(upper, t2)
            if lower <= upper + 1e-12:
                result.add((r, c))
    return result


cases = [(0.5, 0.5, 9.5, 9.5), (0, 4, 9, 4), (3, 0, 3, 9),
         (3, 3, 3, 3), (0.5, 0.5, 9.5, 0.5), (9.9, 9.9, 0.1, 0.1)]
rng = np.random.default_rng(20260923)
cases += [tuple(rng.uniform(0.01, 9.99, 4)) for _ in range(100)]
for case in cases:
    assert set(supercover(*case, (10, 10))) == brute_cells(*case, (10, 10)), case
    assert set(supercover(*case, (10, 10))) == set(supercover(case[2], case[3], case[0], case[1], (10, 10)))

edges = pd.read_csv(OUT / "directed_geometry_edges.csv").set_index(["from_id", "to_id"])
assert len(edges) == 16 * 15 and edges.index.is_unique
for (a, b), row in edges.iterrows():
    rev = edges.loc[(b, a)]
    for col in ["distance_m", "crossed_pixels", "terrain_max_m", "cruise_asl_m"]:
        assert np.isclose(row[col], rev[col])
    assert np.isclose(row.climb_m, rev.descent_m)

summary = json.loads((OUT / "audit_summary.json").read_text(encoding="utf-8"))
boxes = pd.read_csv(OUT / "boxes_with_deadlines.csv")
assert len(boxes) == 80 and boxes["货箱编号"].is_unique
assert summary["demand_reconciliation_mismatches"] == []
assert boxes.loc[boxes["是否首批保障"].eq("否"), "首批截止时间（s）"].isna().all()
for zone in ["S012", "S014"]:
    med = boxes[boxes["服务区编号"].eq(zone) & boxes["物资类型"].eq("医疗物资")]
    assert (med["硬截止时间_s"] == 3600).all()
links = pd.read_csv(OUT / "static_service_gateway_links.csv")
assert set(links.loc[links.direct_available, "zone"]) == {"S001", "S006", "S011"}
assert links.terrain_blocked.all()
result = {"supercover_cases_against_independent_cell_intersection": len(cases),
          "directed_geometry_edges_checked": len(edges),
          "demand_reconciliation": "pass", "deadline_overlap_cases": "pass",
          "scope": "Static preprocessing verification; not full scheduling or continuous-link validation."}
(OUT / "verification.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
print(json.dumps(result, ensure_ascii=False, indent=2))
