"""Read-only audit of the supplied D data; write reproducible derived tables/figures.

Run with E:\\tool\\anaconda3\\python.exe. No package installation is required.
Source spreadsheets/rasters are never modified. This is not an optimization solver.
"""
from pathlib import Path
import hashlib
import json
import math

import numpy as np
import pandas as pd
import scipy.io
import tifffile
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
OUT = Path(__file__).resolve().parent / "audit"
OUT.mkdir(exist_ok=True)
DATA = ROOT / "数据"


def source(name):
    matches = list(DATA.rglob(name))
    if len(matches) != 1:
        raise ValueError((name, matches))
    return matches[0]


def block(df, header, ncols):
    df = df.reset_index(drop=True)
    starts = df.index[df.iloc[:, 0].eq(header)].tolist()
    if len(starts) != 1:
        raise ValueError(f"Ambiguous table header: {header}")
    start = starts[0]
    rows = []
    for row in df.iloc[start + 1:, :ncols].itertuples(index=False, name=None):
        if pd.isna(row[0]) or all(pd.isna(v) for v in row[1:]):
            break
        rows.append(row)
    return pd.DataFrame(rows, columns=df.iloc[start, :ncols].tolist())


def write_csv(df, name):
    df.to_csv(OUT / name, index=False, encoding="utf-8-sig")


def local_xy(lon, lat):
    # A linear metric chart using WGS84 curvature radii at the depot latitude.
    # This preserves straight lines in the source grid, with local scale error
    # below ~0.1% over the task nodes. Original DEM values are not resampled.
    phi = np.deg2rad(23.0085095)
    e2, a = 6.6943799901413165e-3, 6378137.0
    N = a / np.sqrt(1 - e2 * np.sin(phi) ** 2)
    M = a * (1 - e2) / (1 - e2 * np.sin(phi) ** 2) ** 1.5
    return (np.deg2rad(np.asarray(lon) - 109.2308517) * N * np.cos(phi),
            np.deg2rad(np.asarray(lat) - 23.0085095) * M)


def supercover(x0, y0, x1, y1, shape):
    """All closed grid cells touched by a segment, including edge/corner contacts.

    x/y are fractional column/row coordinates relative to OUTER grid corners.
    Splitting at every integer boundary avoids missing narrow pixel intersections.
    """
    ts = [0.0, 1.0]
    for p, q in [(x0, x1), (y0, y1)]:
        if abs(q - p) > 1e-14:
            ks = range(math.floor(min(p, q)) + 1, math.ceil(max(p, q)))
            ts.extend((k - p) / (q - p) for k in ks)
    ts = np.unique(np.clip(ts, 0, 1))
    samples = np.concatenate((ts, (ts[:-1] + ts[1:]) / 2))
    cells = set()
    for t in samples:
        x, y = x0 + t * (x1 - x0), y0 + t * (y1 - y0)
        for dx in [-1e-9, 0, 1e-9]:
            for dy in [-1e-9, 0, 1e-9]:
                c, r = math.floor(x + dx), math.floor(y + dy)
                if 0 <= r < shape[0] and 0 <= c < shape[1]:
                    cells.add((r, c))
    return sorted(cells)


def run():
    manifest = []
    source_paths = list(DATA.rglob("*")) + list(ROOT.glob("*.docx")) + list(ROOT.glob("*.xlsx"))
    for p in sorted(source_paths):
        if p.is_file() and not p.name.startswith("~$"):
            manifest.append({"path": str(p.relative_to(ROOT)), "bytes": p.stat().st_size,
                             "sha256": hashlib.sha256(p.read_bytes()).hexdigest()})
    write_csv(pd.DataFrame(manifest), "source_manifest.csv")
    raw_nodes = pd.read_excel(source("调度中心与服务区.xlsx"), header=None)
    depot = block(raw_nodes, "调度中心编号", 5)
    zones = block(raw_nodes, "服务区编号", 6)
    nodes = pd.DataFrame({"node_id": [depot.iloc[0, 0]] + zones.iloc[:, 0].tolist(),
                          "name": [depot.iloc[0, 1]] + zones.iloc[:, 1].tolist(),
                          "lon": [depot.iloc[0, 2]] + zones.iloc[:, 2].tolist(),
                          "lat": [depot.iloc[0, 3]] + zones.iloc[:, 3].tolist(),
                          "ground_m": [depot.iloc[0, 4]] + zones.iloc[:, 4].tolist(),
                          "population": [0] + zones.iloc[:, 5].tolist()})
    nodes["operation_m"] = nodes.ground_m + np.where(nodes.node_id.eq("O01"), 0, 30)
    nodes["x_m"], nodes["y_m"] = local_xy(nodes.lon, nodes.lat)

    demand = pd.read_excel(source("物资需求与配送时限.xlsx"), sheet_name="数据")
    boxes = pd.read_excel(source("物资需求与配送时限.xlsx"), sheet_name="逐箱货箱清单")
    first = boxes["是否首批保障"].eq("是")
    medical = boxes["物资类型"].eq("医疗物资")
    hard = np.minimum(np.where(first, boxes["首批截止时间（s）"], np.inf),
                      np.where(medical, boxes["期望送达时间（s）"], np.inf))
    boxes["硬截止时间_s"] = np.where(np.isfinite(hard), hard, np.nan)
    boxes["硬时限来源"] = np.select([first & medical, first, medical],
                                           ["首批与医疗取较早值", "首批", "医疗"], default="无")
    write_csv(boxes, "boxes_with_deadlines.csv")
    mismatches = []
    for _, r in demand.iterrows():
        sub = boxes[boxes["服务区编号"].eq(r["服务区编号"]) & boxes["物资类型"].eq(r["物资类型"])]
        checks = {
            "箱数": len(sub) == r["总需求箱数"],
            "首批数": sub["是否首批保障"].eq("是").sum() == r["首批必须送达箱数"],
            "质量": np.allclose(sub["单箱质量（kg）"], r["单箱质量（kg）"]),
            "体积": np.allclose(sub["单箱体积（m³）"], r["单箱体积（m³）"]),
            "优先级": sub["应急优先系数"].eq(r["应急优先系数"]).all(),
            "期望时限": sub["期望送达时间（s）"].eq(r["期望送达时间（s）"]).all(),
            "首批时限": sub.loc[sub["是否首批保障"].eq("是"), "首批截止时间（s）"].eq(r["首批截止时间（s）"]).all(),
        }
        if not all(checks.values()):
            mismatches.append({"zone": r["服务区编号"], "type": r["物资类型"], "checks": checks})
    by_zone = boxes.groupby("服务区编号").agg(
        boxes=("货箱编号", "size"), mass_kg=("单箱质量（kg）", "sum"),
        volume_m3=("单箱体积（m³）", "sum"),
        first_boxes=("是否首批保障", lambda s: s.eq("是").sum()),
        hard_boxes=("硬截止时间_s", "count"), earliest_hard_s=("硬截止时间_s", "min"))
    by_type = boxes.groupby("物资类型").agg(
        boxes=("货箱编号", "size"), mass_kg=("单箱质量（kg）", "sum"),
        volume_m3=("单箱体积（m³）", "sum"),
        first_boxes=("是否首批保障", lambda s: s.eq("是").sum()))
    write_csv(by_zone.reset_index(), "demand_by_zone.csv")
    write_csv(by_type.reset_index(), "demand_by_type.csv")
    raw_fleet = pd.read_excel(source("运输无人机数据.xlsx"), header=None)
    type_start = raw_fleet.index[raw_fleet.iloc[:, 0].eq("三类机型参数")][0]
    type_end = raw_fleet.index[raw_fleet.iloc[:, 0].eq("逐架无人机清单")][0]
    fleet_types = block(raw_fleet.loc[type_start:type_end - 1], "机型编号", 18)
    # Two sections share the same header text. Identify title markers explicitly.
    fleets = block(raw_fleet, "无人机编号", 3)
    idx = raw_fleet.index[raw_fleet.iloc[:, 0].eq("共享电池库存")][0]
    batteries = block(raw_fleet.loc[idx:], "机型编号", 3)
    write_csv(fleet_types, "vehicle_types.csv")
    write_csv(fleets, "vehicles.csv")
    write_csv(batteries, "battery_inventory.csv")
    raw_relay = pd.read_excel(source("中继无人机数据.xlsx"), header=None)
    relay_end = raw_relay.index[raw_relay.iloc[:, 0].eq("逐架中继无人机清单")][0]
    relay_type = block(raw_relay.loc[:relay_end - 1], "机型编号", 19)
    relay_vehicles = block(raw_relay, "中继无人机编号", 3)
    relay_inv_start = raw_relay.index[raw_relay.iloc[:, 0].eq("共享能源组件库存")][0]
    relay_inventory = block(raw_relay.loc[relay_inv_start:], "机型编号", 3)
    write_csv(relay_type, "relay_types.csv")
    write_csv(relay_vehicles, "relay_vehicles.csv")
    write_csv(relay_inventory, "relay_component_inventory.csv")
    raw_comm = pd.read_excel(source("通信链路参数.xlsx"), header=None)
    comm = block(raw_comm, "参数类别", 5).dropna(axis=1, how="all")
    write_csv(comm, "communication_parameters.csv")

    def param(category, name):
        selected = comm[comm["参数类别"].eq(category) & comm["参数名称"].eq(name)]
        if len(selected) != 1:
            raise ValueError((category, name))
        return float(selected.iloc[0]["参数值"])

    frequency = param("传播参数", "载波频率（MHz）")
    system_loss = param("传播参数", "系统损耗（dB）")
    obstruction_loss = param("传播参数", "地形遮挡附加损耗（dB）")
    threshold = param("接收参数", "接收灵敏度（dBm）") + param("接收参数", "衰落裕量（dB）")

    m = scipy.io.loadmat(source("镇龙乡及周边30米DEM.mat"))
    dem = m["dem"]
    lons, lats = m["longitude"].ravel(), m["latitude"].ravel()
    transform = m["transform"].ravel()
    dx, _, left, _, dy, top = transform
    valid = np.isfinite(dem) & (dem != m["nodata"].item())
    with tifffile.TiffFile(source("镇龙乡及周边30米DEM.tif")) as t:
        tif_equal = bool(np.array_equal(t.asarray(), dem))
        raster_tags = {k: list(t.pages[0].tags[k].value) for k in
                       ["ModelTiepointTag", "ModelPixelScaleTag", "GeoKeyDirectoryTag"]}
    cols = (nodes.lon.to_numpy() - left) / dx
    rows = (nodes.lat.to_numpy() - top) / dy
    inside = (cols >= 0) & (cols < dem.shape[1]) & (rows >= 0) & (rows < dem.shape[0])
    assert inside.all(), "Node outside DEM"
    nodes["dem_row"] = np.floor(rows).astype(int)
    nodes["dem_col"] = np.floor(cols).astype(int)
    nodes["dem_pixel_m"] = dem[nodes.dem_row, nodes.dem_col]
    nodes["dem_minus_given_m"] = nodes.dem_pixel_m - nodes.ground_m
    write_csv(nodes, "nodes_audit.csv")
    edges = []
    for i in range(len(nodes)):
        for j in range(i + 1, len(nodes)):
            cells = supercover(cols[i], rows[i], cols[j], rows[j], dem.shape)
            terrain = np.array([dem[r, c] for r, c in cells])
            if not np.isfinite(terrain).all() or (terrain == m["nodata"].item()).any():
                raise ValueError("NoData on task segment")
            zmax = float(terrain.max())
            height = zmax + 50
            dist = float(np.hypot(nodes.x_m[i] - nodes.x_m[j], nodes.y_m[i] - nodes.y_m[j]))
            for a, b in [(i, j), (j, i)]:
                up, down = height - nodes.operation_m[a], height - nodes.operation_m[b]
                # Fail visibly instead of silently changing the contest altitude rule.
                if min(up, down) < 0:
                    raise ValueError("Cruise altitude below a supplied endpoint operation altitude")
                edges.append({"from_id": nodes.node_id[a], "to_id": nodes.node_id[b],
                              "distance_m": dist, "crossed_pixels": len(cells),
                              "terrain_max_m": zmax, "cruise_asl_m": height,
                              "climb_m": up, "descent_m": down})
    edges = pd.DataFrame(edges)
    write_csv(edges, "directed_geometry_edges.csv")
    depot_edges = edges[edges.from_id.eq("O01")].copy()
    write_csv(depot_edges, "depot_outbound_geometry.csv")

    geography = []
    for p in sorted(DATA.rglob("*.csv")):
        d = pd.read_csv(p)
        idcol = d.columns[0]
        g = {"file": p.name, "rows": len(d), "cols": len(d.columns),
             "features": int(d[idcol].nunique()), "null_cells": int(d.isna().sum().sum()),
             "full_duplicate_rows": int(d.duplicated().sum()),
             "unique_osm": int(d["OSM编号"].nunique())}
        if "多边形编号" in d:
            keys = [idcol, "多边形编号", "环编号"]
            g["rings"] = d.groupby(keys).ngroups
            g["polygons"] = d.groupby([idcol, "多边形编号"]).ngroups
        elif "点序号" in d:
            keys = [idcol]
        else:
            keys = None
        if keys:
            g["duplicate_sequence_keys"] = int(d.duplicated(keys + ["点序号"]).sum())
            g["noncontiguous_sequences"] = 0
            g["unclosed_rings"] = 0
            for _, part in d.groupby(keys):
                part = part.sort_values("点序号")
                if not np.array_equal(part["点序号"].to_numpy(), np.arange(1, len(part) + 1)):
                    g["noncontiguous_sequences"] += 1
                if "环编号" in d and not np.allclose(part.iloc[0][["经度", "纬度"]].astype(float),
                                                      part.iloc[-1][["经度", "纬度"]].astype(float),
                                                      rtol=0, atol=1e-10):
                    g["unclosed_rings"] += 1
        if "长度_km" in d:
            g["length_km_feature_once"] = float(d.groupby(idcol)["长度_km"].first().sum())
            g["within_feature_length_conflicts"] = int((d.groupby(idcol)["长度_km"].nunique() > 1).sum())
        geography.append(g)
    write_csv(pd.DataFrame(geography), "geography_inventory.csv")
    link_rows = []
    for label, a, b in [("transport_gateway", "运输无人机", "固定网关 G01"),
                        ("transport_relay_access", "运输无人机", "中继接入端"),
                        ("relay_backhaul_gateway", "中继回传端", "固定网关 G01")]:
        pa, ga = param(a, "发射功率（dBm）"), param(a, "天线增益（dBi）")
        pb, gb = param(b, "发射功率（dBm）"), param(b, "天线增益（dBi）")
        budget_ab = pa + ga + gb - system_loss - threshold
        budget_ba = pb + gb + ga - system_loss - threshold
        budget = min(budget_ab, budget_ba)
        distance_km = 10 ** ((budget - 32.45 - 20 * math.log10(frequency)) / 20)
        link_rows.append({"link": label, "budget_a_to_b_db": budget_ab,
                          "budget_b_to_a_db": budget_ba, "bidirectional_budget_db": budget,
                          "los_distance_km": distance_km, "blocked_distance_km": distance_km / 10 ** (obstruction_loss / 20)})
    write_csv(pd.DataFrame(link_rows), "link_budget_thresholds.csv")
    endpoint_links = []
    gateway_z = float(nodes.ground_m[0] + param("固定网关 G01", "天线离地高度（m）"))
    direct_budget = next(row["bidirectional_budget_db"] for row in link_rows if row["link"] == "transport_gateway")
    for j in range(1, len(nodes)):
        clearances = []
        for r, c in supercover(cols[0], rows[0], cols[j], rows[j], dem.shape):
            enter, leave = 0.0, 1.0
            for p0, p1, lo, hi in [(cols[0], cols[j], c, c + 1),
                                   (rows[0], rows[j], r, r + 1)]:
                if abs(p1 - p0) > 1e-14:
                    a, b = sorted([(lo - p0) / (p1 - p0), (hi - p0) / (p1 - p0)])
                    enter, leave = max(enter, a), min(leave, b)
            if enter <= leave + 1e-10:
                z1 = gateway_z + enter * (nodes.operation_m[j] - gateway_z)
                z2 = gateway_z + leave * (nodes.operation_m[j] - gateway_z)
                clearances.append(min(z1, z2) - float(dem[r, c]))
        minimum = min(clearances)
        blocked = minimum <= 0
        distance_km = math.sqrt(nodes.x_m[j] ** 2 + nodes.y_m[j] ** 2 +
                                (nodes.operation_m[j] - gateway_z) ** 2) / 1000
        loss = 32.45 + 20 * math.log10(frequency) + 20 * math.log10(distance_km) + obstruction_loss * blocked
        endpoint_links.append({"zone": nodes.node_id[j], "operation_asl_m": nodes.operation_m[j],
                               "distance_3d_km": distance_km, "min_terrain_clearance_m": minimum,
                               "terrain_blocked": bool(blocked), "link_margin_db": direct_budget - loss,
                               "direct_available": bool(loss <= direct_budget)})
    write_csv(pd.DataFrame(endpoint_links), "static_service_gateway_links.csv")
    capacity_rows = []
    for _, f in fleet_types.iterrows():
        for typ, sub in boxes.groupby("物资类型"):
            mass, volume = sub.iloc[0]["单箱质量（kg）"], sub.iloc[0]["单箱体积（m³）"]
            n_mass = int(float(f["最大载货质量（kg）"]) // mass)
            n_volume = math.floor(float(f["可用装载体积（m³）"]) / volume + 1e-10)
            capacity_rows.append({"type": f["机型编号"], "commodity": typ,
                                  "mass_limit_boxes": n_mass, "volume_limit_boxes": n_volume,
                                  "capacity_ignoring_energy": min(n_mass, n_volume)})
    write_csv(pd.DataFrame(capacity_rows), "single_commodity_capacity.csv")

    summary = {"nodes": len(nodes), "zones": len(zones), "population": int(nodes.population.sum()),
               "demand_records": len(demand), "boxes": len(boxes),
               "mass_kg": float(boxes["单箱质量（kg）"].sum()),
               "volume_m3": float(boxes["单箱体积（m³）"].sum()),
               "first_boxes": int(first.sum()), "medical_boxes": int(medical.sum()),
               "hard_deadline_boxes": int(np.isfinite(hard).sum()),
               "structural_empty_first_deadlines": int(boxes.loc[~first, "首批截止时间（s）"].isna().sum()),
               "missing_required_first_deadline": int(boxes.loc[first, "首批截止时间（s）"].isna().sum()),
               "duplicate_box_ids": int(boxes["货箱编号"].duplicated().sum()),
               "unknown_zone_ids": sorted(set(boxes["服务区编号"]) - set(nodes.node_id)),
               "demand_reconciliation_mismatches": mismatches,
               "hard_deadline_distribution": boxes["硬截止时间_s"].value_counts().sort_index().to_dict(),
               "dem": {"shape": list(dem.shape), "pixels": int(dem.size),
                       "invalid_pixels": int((~valid).sum()), "tif_mat_equal": tif_equal,
                       "min_m": float(dem[valid].min()), "max_m": float(dem[valid].max()),
                       "mean_m": float(dem[valid].mean()),
                       "percentiles_m": np.percentile(dem[valid], [5, 25, 50, 75, 95]).tolist(),
                       "center_lon_range": [float(lons.min()), float(lons.max())],
                       "center_lat_range": [float(lats.min()), float(lats.max())],
                       "tif_tags": raster_tags,
                       "all_nodes_inside": bool(inside.all()),
                       "node_dem_difference_min_m": float(nodes.dem_minus_given_m.min()),
                       "node_dem_difference_max_m": float(nodes.dem_minus_given_m.max())},
               "depot_distances_m": {"min": float(depot_edges.distance_m.min()),
                                     "max": float(depot_edges.distance_m.max())},
               "geometry_edges": len(edges), "geography": geography,
               "vehicle_count": len(fleets), "battery_count": int(batteries.iloc[:, 1].sum()),
               "relay_vehicle_count": len(relay_vehicles), "relay_component_count": int(relay_inventory.iloc[:, 1].sum()),
               "link_budgets": link_rows,
               "static_service_direct_available": sum(r["direct_available"] for r in endpoint_links),
               "static_service_terrain_blocked": sum(r["terrain_blocked"] for r in endpoint_links),
               "limitations": ["Geometry uses a linear WGS84 local metric chart, not a full projected CRS.",
                               "No demand, geometry or physical parameter is corrected automatically.",
                               "No energy optimization or continuous communication feasibility has been claimed.",
                               "Remaining XLSX schemas and full DOCX/PDF rules are reviewed separately."]}
    (OUT / "audit_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    plt.rcParams.update({"font.sans-serif": ["Microsoft YaHei", "SimHei", "DejaVu Sans"],
                         "axes.unicode_minus": False, "font.size": 10})
    fig, axs = plt.subplots(2, 2, figsize=(13, 10), constrained_layout=True)
    xlim = [nodes.lon.min() - .018, nodes.lon.max() + .018]
    ylim = [nodes.lat.min() - .018, nodes.lat.max() + .018]
    im = axs[0, 0].imshow(dem, extent=[left, left + dx * dem.shape[1], top + dy * dem.shape[0], top],
                          origin="upper", cmap="terrain", aspect=1 / np.cos(np.deg2rad(23)))
    axs[0, 0].set(xlim=xlim, ylim=ylim, title="任务节点与原始 DSM 地形", xlabel="经度", ylabel="纬度")
    axs[0, 0].scatter(nodes.lon[1:], nodes.lat[1:], s=25, c="#1e293b")
    axs[0, 0].scatter(nodes.lon[0], nodes.lat[0], marker="*", s=150, c="#dc2626")
    for _, n in nodes.iterrows():
        axs[0, 0].annotate(n.node_id, (n.lon, n.lat), xytext=(3, 3), textcoords="offset points", fontsize=8)
    fig.colorbar(im, ax=axs[0, 0], label="表面高程 / m", fraction=.03)
    pivot = boxes.pivot_table(index="服务区编号", columns="物资类型", values="货箱编号", aggfunc="count", fill_value=0)
    pivot.plot.bar(stacked=True, ax=axs[0, 1], width=.8, color=["#2c7bb6", "#fdae61", "#74add1", "#d7191c"])
    axs[0, 1].set(title="逐服务区货箱结构（不可拆分）", ylabel="箱数", xlabel="")
    axs[0, 1].legend(fontsize=8)
    ordered = depot_edges.sort_values("distance_m")
    axs[1, 0].scatter(ordered.distance_m / 1000, ordered.climb_m, c="#2563eb")
    for _, e in ordered.iterrows():
        axs[1, 0].annotate(e.to_id, (e.distance_m / 1000, e.climb_m), fontsize=8, xytext=(3, 3), textcoords="offset points")
    axs[1, 0].set(title="O01 出发距离与爬升需求", xlabel="水平距离 / km", ylabel="爬升高度 / m")
    first_counts = boxes.loc[first, "首批截止时间（s）"].value_counts().sort_index()
    medical_counts = boxes.loc[medical, "期望送达时间（s）"].value_counts().sort_index()
    deadline_plot = pd.DataFrame({"首批硬时限": first_counts, "医疗硬时限": medical_counts}).fillna(0)
    deadline_plot.index = [f"{int(t / 60)}" for t in deadline_plot.index]
    deadline_plot.plot.bar(ax=axs[1, 1], color=["#d97706", "#7c3aed"])
    axs[1, 1].set(title="两类硬时限分布（同一箱可能重复计入）", xlabel="任务起点后的分钟数", ylabel="箱数")
    fig.savefig(OUT / "data_overview.png", dpi=180)
    plt.close(fig)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    run()
