"""Problem 1: physical model and exact count-pattern integer programming.

Identical boxes within the same service area are interchangeable in Q1 only.
All feasible count patterns are enumerated; integer multiplicities can then be
expanded into individually labelled boxes without changing objectives.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import warnings
import hashlib
import itertools
import json
import math
import time

# Isolate MKL from PyTorch's OpenMP runtime; never enable KMP_DUPLICATE_LIB_OK.
os.environ["MKL_THREADING_LAYER"] = "SEQUENTIAL"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

import numpy as np
import pandas as pd
from scipy.io import loadmat
from scipy.optimize import Bounds, LinearConstraint, linprog, milp
from scipy.sparse import csc_matrix, hstack, vstack

ROOT = Path(__file__).resolve().parent.parent
WORK = Path(__file__).resolve().parent
DATA = ROOT / "D题" / "数据"
G = 9.81
J_PER_KWH = 3.6e6
FEAS_TOL = 1e-9
OBJECTIVE_TOL = np.array([0.1, 1e-7, 1e-4])


def highs_milp(*args, **kwargs):
    # SciPy forwards this documented HiGHS option but warns it is not in its
    # shorter public option list. Each independent process owns one solver.
    kwargs.setdefault("options", {})["threads"] = 1
    kwargs["options"]["mip_feasibility_tolerance"] = 1e-9
    kwargs["options"]["primal_feasibility_tolerance"] = 1e-9
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="Unrecognized options detected")
        return milp(*args, **kwargs)


def source(name):
    paths = list(DATA.rglob(name))
    if len(paths) != 1:
        raise ValueError((name, paths))
    return paths[0]


def block(df, header, ncols):
    df = df.reset_index(drop=True)
    start, = df.index[df.iloc[:, 0].eq(header)]
    rows = []
    for row in df.iloc[start + 1:, :ncols].itertuples(index=False, name=None):
        if pd.isna(row[0]) or all(pd.isna(v) for v in row[1:]):
            break
        rows.append(row)
    return pd.DataFrame(rows, columns=df.iloc[start, :ncols].tolist())


def local_xy(lon, lat, lon0, lat0):
    """Local WGS84 metric chart, same convention as existing preprocessing."""
    phi = np.deg2rad(lat0)
    e2, a = 6.6943799901413165e-3, 6378137.
    n = a / np.sqrt(1 - e2 * np.sin(phi)**2)
    m = a * (1 - e2) / (1 - e2 * np.sin(phi)**2)**1.5
    return (np.deg2rad(np.asarray(lon) - lon0) * n * np.cos(phi),
            np.deg2rad(np.asarray(lat) - lat0) * m)


def supercover(x0, y0, x1, y1, shape):
    """Every closed DEM pixel touched by a straight segment; no resampling."""
    ts = [0., 1.]
    for p, q in [(x0, x1), (y0, y1)]:
        if abs(q - p) > 1e-14:
            ts.extend((k - p) / (q - p) for k in
                      range(math.floor(min(p, q)) + 1, math.ceil(max(p, q))))
    ts = np.unique(np.clip(ts, 0, 1))
    samples = np.r_[ts, (ts[:-1] + ts[1:]) / 2]
    cells = set()
    for t in samples:
        x, y = x0 + t * (x1 - x0), y0 + t * (y1 - y0)
        for dx, dy in itertools.product([-1e-9, 0, 1e-9], repeat=2):
            c, r = math.floor(x + dx), math.floor(y + dy)
            if 0 <= r < shape[0] and 0 <= c < shape[1]:
                cells.add((r, c))
    return sorted(cells)


@dataclass(frozen=True)
class Vehicle:
    name: str
    empty: float
    capacity: float
    volume: float
    speed: float
    range_empty: float
    range_full: float
    battery: float
    rho: float
    prep: float
    load: float
    handoff_base: float
    handoff_box: float
    up_speed: float
    down_speed: float
    eta: float


def load_inputs():
    path_nodes = source("调度中心与服务区.xlsx")
    raw = pd.read_excel(path_nodes, header=None)
    depot = block(raw, "调度中心编号", 5).iloc[0]
    zones = block(raw, "服务区编号", 6)
    nodes = pd.DataFrame({
        "zone": [depot.iloc[0]] + zones.iloc[:, 0].tolist(),
        "lon": [depot.iloc[2]] + zones.iloc[:, 2].tolist(),
        "lat": [depot.iloc[3]] + zones.iloc[:, 3].tolist(),
        "ground_m": [depot.iloc[4]] + zones.iloc[:, 4].tolist()})
    nodes["operation_m"] = nodes.ground_m + np.where(nodes.zone.eq("O01"), 0, 30)
    nodes["x_m"], nodes["y_m"] = local_xy(nodes.lon, nodes.lat,
                                         nodes.lon.iloc[0], nodes.lat.iloc[0])
    path_fleet = source("运输无人机数据.xlsx")
    raw = pd.read_excel(path_fleet, header=None)
    end, = raw.index[raw.iloc[:, 0].eq("逐架无人机清单")]
    table = block(raw.iloc[:end], "机型编号", 18)
    vehicles = {}
    for row in table.itertuples(index=False, name=None):
        vehicles[row[0]] = Vehicle(
            row[0], *map(float, row[2:9]), float(row[9]) / 100,
            *map(float, row[10:17]))
    path_boxes = source("物资需求与配送时限.xlsx")
    boxes = pd.read_excel(path_boxes, sheet_name="逐箱货箱清单").rename(columns={
        "货箱编号": "box", "服务区编号": "zone", "物资类型": "kind",
        "单箱质量（kg）": "mass", "单箱体积（m³）": "volume"})
    assert len(boxes) == 80 and boxes.box.is_unique and boxes.zone.nunique() == 15
    path_dem = source("镇龙乡及周边30米DEM.mat")
    raster = loadmat(path_dem)
    dem, tr = raster["dem"], raster["transform"].ravel()
    dx, _, left, _, dy, top = tr
    cs = (nodes.lon.to_numpy() - left) / dx
    rs = (nodes.lat.to_numpy() - top) / dy
    assert np.all((cs >= 0) & (cs < dem.shape[1]) & (rs >= 0) & (rs < dem.shape[0]))
    geometry = []
    for j in range(1, len(nodes)):
        cells = supercover(cs[0], rs[0], cs[j], rs[j], dem.shape)
        z = np.array([dem[r, c] for r, c in cells])
        assert np.isfinite(z).all() and not (z == raster["nodata"].item()).any()
        height = float(z.max()) + 50
        hu = height - nodes.operation_m.iloc[0]
        hd = height - nodes.operation_m.iloc[j]
        assert min(hu, hd) >= 0
        geometry.append(dict(zone=nodes.zone.iloc[j],
                             distance_m=float(np.hypot(nodes.x_m.iloc[j], nodes.y_m.iloc[j])),
                             terrain_max_m=float(z.max()), cruise_m=height,
                             outbound_up_m=hu, outbound_down_m=hd,
                             crossed_pixels=len(cells)))
    inputs = [path_nodes, path_fleet, path_boxes, path_dem,
              ROOT / "D题" / "山区洪涝灾害下无人机运输与通信协同优化.docx",
              ROOT / "D题" / "结果提交模板.xlsx"]
    manifest = [dict(path=str(p.relative_to(ROOT)), bytes=p.stat().st_size,
                     sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in inputs]
    return boxes, vehicles, pd.DataFrame(geometry), nodes, manifest


def flight(v, geo, q, eta=None):
    eta = v.eta if eta is None else eta
    length = v.range_empty - (v.range_empty - v.range_full) * (q / v.capacity)**1.5
    d, hu, hd = geo["distance_m"], geo["outbound_up_m"], geo["outbound_down_m"]
    eh_out = v.battery * d / length
    eh_back = v.battery * d / v.range_empty
    eu_out = (v.empty + q) * G * hu / (eta * J_PER_KWH)
    eu_back = v.empty * G * hd / (eta * J_PER_KWH)
    fly_out = hu / v.up_speed + d / v.speed + hd / v.down_speed
    fly_back = hd / v.up_speed + d / v.speed + hu / v.down_speed
    return dict(energy=eh_out + eh_back + eu_out + eu_back,
                horizontal_energy=eh_out + eh_back, climb_energy=eu_out + eu_back,
                out_s=fly_out, back_s=fly_back, fly_s=fly_out + fly_back)


def safe_load(v, geo, rho, eta=None):
    budget = (1 - rho) * v.battery
    if flight(v, geo, 0, eta)["energy"] > budget + FEAS_TOL:
        return np.nan, "不可达"
    if flight(v, geo, v.capacity, eta)["energy"] <= budget + FEAS_TOL:
        return v.capacity, "额定载荷受限"
    lo, hi = 0., v.capacity
    for _ in range(65):
        mid = (lo + hi) / 2
        if flight(v, geo, mid, eta)["energy"] <= budget:
            lo = mid
        else:
            hi = mid
    return lo, "能量受限"


def capacity_table(vehicles, geometry, rho=.2, eta=None):
    out = []
    for geo in geometry.to_dict("records"):
        for v in vehicles.values():
            q, flag = safe_load(v, geo, rho, eta)
            out.append(dict(zone=geo["zone"], vehicle=v.name, rho=rho, eta=eta or v.eta,
                            safe_load_kg=q, status=flag, capacity_kg=v.capacity,
                            energy_empty=flight(v, geo, 0, eta)["energy"],
                            energy_full=flight(v, geo, v.capacity, eta)["energy"]))
    return pd.DataFrame(out)


def generate_patterns(boxes, vehicles, geometry):
    """Full mass/volume-feasible universe, before any SOC filtering."""
    all_patterns, demands, identities = [], {}, {}
    for geo in geometry.to_dict("records"):
        zone = geo["zone"]
        bz = boxes[boxes.zone.eq(zone)].copy()
        groups = list(bz.groupby(["mass", "volume"], sort=True))
        keys, counts, masses, volumes = [], [], [], []
        for t, ((mass, volume), group) in enumerate(groups):
            key = f"{zone}:T{t}"
            keys.append(key)
            counts.append(len(group))
            masses.append(float(mass))
            volumes.append(float(volume))
            identities[key] = sorted(group.box.tolist())
            demands[key] = len(group)
        for count in itertools.product(*(range(n + 1) for n in counts)):
            nbox = sum(count)
            if nbox == 0:
                continue
            q = float(np.dot(count, masses))
            volume = float(np.dot(count, volumes))
            comb = math.prod(math.comb(n, k) for n, k in zip(counts, count))
            for v in vehicles.values():
                if q > v.capacity + FEAS_TOL or volume > v.volume + FEAS_TOL:
                    continue
                f = flight(v, geo, q)
                handoff = v.handoff_base + nbox * v.handoff_box
                prep_load = v.prep + nbox * v.load
                all_patterns.append(dict(
                    pattern=f"P{len(all_patterns)+1:05}", zone=zone, vehicle=v.name,
                    counts={key: k for key, k in zip(keys, count) if k},
                    nbox=nbox, mass=q, volume=volume, combinations=comb,
                    ub=min(n // k for n, k in zip(counts, count) if k),
                    prep_load_s=prep_load, handoff_s=handoff,
                    operation_s=prep_load + handoff + f["fly_s"],
                    battery=v.battery, rho_crit=1 - f["energy"] / v.battery, **f))
    return all_patterns, demands, identities


def active_patterns(universe, rho=.2, eta=.72):
    active, raw = [], []
    for p in universe:
        p = p.copy()
        p["climb_energy"] = p["climb_energy"] * .72 / eta
        p["energy"] = p["horizontal_energy"] + p["climb_energy"]
        p["rho_crit"] = 1 - p["energy"] / p["battery"]
        if p["rho_crit"] + FEAS_TOL >= rho:
            raw.append(p)
    by_counts = {}
    for p in raw:
        by_counts.setdefault(tuple(p["counts"].items()), []).append(p)
    for ps in by_counts.values():
        for p in ps:
            # Safe only in Q1: type availability and battery scheduling absent.
            dominated = any(
                other["energy"] <= p["energy"] + 1e-10
                and other["operation_s"] <= p["operation_s"] + 1e-7
                and (other["energy"] < p["energy"] - 1e-10
                     or other["operation_s"] < p["operation_s"] - 1e-7)
                for other in ps if other is not p)
            if not dominated:
                active.append(p)
    return sorted(active, key=lambda p: p["pattern"]), raw


class Model:
    def __init__(self, patterns, demands, log=None, scenario="base"):
        self.patterns = patterns
        self.keys = list(demands)
        self.b = np.array(list(demands.values()), dtype=float)
        self.A = csc_matrix([[p["counts"].get(k, 0) for p in patterns] for k in self.keys])
        self.C = np.array([[1., p["energy"], p["operation_s"]] for p in patterns]).T
        self.ub = np.array([p["ub"] for p in patterns], dtype=float)
        self.log = log if log is not None else []
        self.scenario = scenario

    def solve(self, cost, caps=(), lp=False, tag=""):
        begin = time.perf_counter()
        cost = np.asarray(cost, dtype=float)
        if not len(self.patterns):
            return None
        if lp:
            extra = csc_matrix(np.array([a for a, b in caps])) if caps else None
            out = linprog(cost, A_ub=extra,
                          b_ub=np.array([b for a, b in caps]) if caps else None,
                          A_eq=self.A, b_eq=self.b, bounds=list(zip(np.zeros(len(cost)), self.ub)),
                          method="highs",
                          options={"dual_feasibility_tolerance": 1e-9,
                                   "primal_feasibility_tolerance": 1e-9})
        else:
            cons = [LinearConstraint(self.A, self.b, self.b)]
            if caps:
                cons.append(LinearConstraint(csc_matrix(np.array([a for a, b in caps])),
                                             -np.inf, [b for a, b in caps]))
            out = highs_milp(cost, integrality=np.ones(len(cost)), bounds=Bounds(0, self.ub),
                       constraints=cons, options={"mip_rel_gap": 1e-9, "time_limit": 120.})
        record = dict(scenario=self.scenario, tag=tag, relaxation=lp, status=int(out.status),
                      seconds=time.perf_counter() - begin,
                      objective=float(out.fun) if out.fun is not None else None,
                      dual_bound=float(out.get("mip_dual_bound") if out.get("mip_dual_bound") is not None else np.nan),
                      mip_gap=float(out.get("mip_gap") if out.get("mip_gap") is not None else np.nan),
                      nodes=int(out.get("mip_node_count", 0) or 0))
        self.log.append(record)
        if out.status == 2:
            return None
        if not out.success:
            raise RuntimeError(f"Uncertified solve ({self.scenario}/{tag}): {out.message}")
        x = out.x if lp else np.rint(out.x)
        if not lp:
            assert np.max(np.abs(self.A @ x - self.b)) < 1e-7
            assert np.all((x >= 0) & (x <= self.ub))
            for a, bound in caps:
                assert a @ x <= bound + 3e-5, (tag, a @ x, bound)
        return x, self.C @ x, float(cost @ x)

    def lex(self, order, caps=(), tag=""):
        caps = list(caps)
        result = None
        for r in order:
            result = self.solve(self.C[r] / [1, 1, 1000][r], caps=caps,
                                tag=f"{tag}/lex{r}")
            if result is None:
                return None
            caps.append((self.C[r], result[1][r] + OBJECTIVE_TOL[r]))
        return result

    def weighted(self, w, scale, tag="weighted"):
        return self.solve(np.asarray(w) / scale @ self.C, tag=tag)

    def robust(self, weights, scale, ideal, optima, tag="robust"):
        """Global minimax regret over the FULL integer feasible set."""
        begin = time.perf_counter()
        coeff = weights / scale @ self.C
        # Constant ideal offsets cancel from regret.
        best_uncentered = optima + weights @ (ideal / scale)
        n = len(self.patterns)
        mat = vstack([hstack([self.A, csc_matrix((len(self.b), 1))]),
                      hstack([csc_matrix(coeff), csc_matrix(-np.ones((len(weights), 1)))])],
                     format="csc")
        cons = LinearConstraint(mat, np.r_[self.b, np.full(len(weights), -np.inf)],
                                np.r_[self.b, best_uncentered])
        result = highs_milp(np.r_[np.zeros(n), 1.], integrality=np.r_[np.ones(n), 0],
                      bounds=Bounds(np.zeros(n+1), np.r_[self.ub, np.inf]),
                      constraints=cons, options={"mip_rel_gap": 1e-9, "time_limit": 180.})
        self.log.append(dict(scenario=self.scenario, tag=tag, relaxation=False,
                             status=int(result.status), seconds=time.perf_counter()-begin,
                             objective=float(result.fun) if result.fun is not None else None,
                             dual_bound=float(result.get("mip_dual_bound") if result.get("mip_dual_bound") is not None else np.nan),
                             mip_gap=float(result.get("mip_gap") if result.get("mip_gap") is not None else np.nan),
                             nodes=int(result.get("mip_node_count", 0) or 0)))
        if result.status == 2:
            return None
        if not result.success:
            raise RuntimeError(f"Uncertified minimax solve: {result.message}")
        rstar = result.fun
        caps = [(coeff[i], best_uncentered[i] + rstar + 1e-8) for i in range(len(weights))]
        # Positive tie-break objective gives a Pareto representative.
        tie = self.solve(np.ones(3) / scale @ self.C, caps=caps, tag=tag+"/Pareto-tie")
        x, f, _ = tie
        regret = (weights @ ((f - ideal) / scale)) - optima
        return dict(x=x, f=f, regret=float(regret.max()), solver_lower_bound=rstar,
                    worst_vertex=int(np.argmax(regret)))


def preference_vertices(center=(1/3, 1/3, 1/3), delta=1/3):
    """Intersect all supporting half-spaces of the L1 ball with the simplex."""
    c = np.asarray(center)
    assert np.isclose(c.sum(), 1) and min(c) >= 0 and delta >= 0
    if delta == 0:
        return c[None, :]
    a = np.r_[-np.eye(3), np.array(list(itertools.product([-1., 1.], repeat=3)))]
    b = np.r_[np.zeros(3), delta + a[3:] @ c]
    vertices = []
    for i, j in itertools.combinations(range(len(a)), 2):
        mat = np.vstack([np.ones(3), a[i], a[j]])
        if abs(np.linalg.det(mat)) < 1e-10:
            continue
        v = np.linalg.solve(mat, [1, b[i], b[j]])
        if np.all(a @ v <= b + 1e-9) and not any(np.allclose(v, u, atol=1e-8) for u in vertices):
            vertices.append(np.clip(v, 0, 1))
    return np.array(sorted(vertices, key=lambda w: tuple(w)))


def minimax(model, ideal, scale, delta=1/3, center=(1/3, 1/3, 1/3)):
    weights = preference_vertices(center, delta)
    optima, supported = [], []
    for i, w in enumerate(weights):
        result = model.weighted(w, scale, tag=f"vertex-d{delta:.5f}-{i}")
        if result is None:
            return None
        x, f, value = result
        optima.append(float(w @ ((f - ideal) / scale)))
        supported.append(dict(x=x, f=f))
    optima = np.array(optima)
    result = model.robust(weights, scale, ideal, optima, tag=f"minimax-d{delta:.5f}")
    result.update(weights=weights, optima=optima, supported=supported)
    return result


def dominates(a, b):
    return np.all(a <= b + OBJECTIVE_TOL) and np.any(a < b - OBJECTIVE_TOL)


def archive_insert(archive, x, f):
    if any(np.all(np.abs(p["f"] - f) <= OBJECTIVE_TOL) or dominates(p["f"], f) for p in archive):
        return
    archive[:] = [p for p in archive if not dominates(f, p["f"])]
    archive.append(dict(x=x.copy(), f=f.copy()))


def expand_plan(model, x, identities, rho=.2):
    pools = {k: list(v) for k, v in identities.items()}
    plan = []
    for p, multiplicity in zip(model.patterns, np.rint(x).astype(int)):
        for _ in range(multiplicity):
            boxes = []
            for key, n in p["counts"].items():
                assert len(pools[key]) >= n
                boxes.extend(pools[key][:n])
                pools[key] = pools[key][n:]
            plan.append(dict(sortie=f"Q1-{len(plan)+1:03}", zone=p["zone"],
                             vehicle=p["vehicle"], boxes=sorted(boxes),
                             mass=p["mass"], volume=p["volume"],
                             fly_s=p["fly_s"], operation_s=p["operation_s"],
                             prep_load_s=p["prep_load_s"], handoff_s=p["handoff_s"],
                             energy=p["energy"], horizontal_energy=p["horizontal_energy"],
                             climb_energy=p["climb_energy"],
                             return_soc=1 - p["energy"] / p["battery"],
                             pattern=p["pattern"], rho=rho))
    assert not any(pools.values())
    return plan


def json_ready(obj):
    if isinstance(obj, np.ndarray):
        return [json_ready(x) for x in obj.tolist()]
    if isinstance(obj, dict):
        return {str(k): json_ready(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [json_ready(x) for x in obj]
    if isinstance(obj, (np.integer, np.floating)):
        return obj.item()
    return obj


def save_json(path, obj):
    Path(path).write_text(json.dumps(json_ready(obj), ensure_ascii=False, indent=2),
                          encoding="utf-8")


def csv(path, records):
    pd.DataFrame(records).to_csv(path, index=False, encoding="utf-8-sig")
