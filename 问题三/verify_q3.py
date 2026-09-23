"""Independent physical and scheduling verifier for the Q3 joint plan.

The verifier rebuilds route geometry, energy, time, box delivery, resource
intervals and continuous communication certificates from the raw attachments.
It does not reuse the MILP's cached masks or objective values.
"""
from __future__ import annotations
import os
os.environ["MKL_THREADING_LAYER"] = "SEQUENTIAL"
for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_k] = "1"
import json, math, sys
from pathlib import Path
from collections import defaultdict

import numpy as np
import pandas as pd
from scipy.io import loadmat

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
from q3_inputs import read_inputs, all_geometry, seg, charge, local_xy, supercover
from q3_common import sweep_clear

PLAN_PATH = HERE / "子问题二" / "最终方案_待独立核验.json"
OUT_PATH = HERE / "子问题二" / "独立核验结果.json"
DETAIL_PATH = HERE / "子问题二" / "独立核验明细.csv"
TOL = 2e-4
ETOL = 2e-6


def finite(x):
    try:
        return bool(np.isfinite(float(x)))
    except Exception:
        return False


def interval_overlap(a0, a1, b0, b1, tol=TOL):
    return max(a0, b0) < min(a1, b1) - tol


def pairwise_conflicts(items, begin, end):
    out = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if interval_overlap(float(items[i][begin]), float(items[i][end]),
                                float(items[j][begin]), float(items[j][end])):
                out.append((items[i], items[j]))
    return out


class Verifier:
    def __init__(self, plan):
        _, self.boxes, self.vs, self.nodes, _ = read_inputs()
        self.geos = all_geometry(self.nodes)
        raw = loadmat(next((ROOT / "D题" / "数据").rglob("镇龙乡及周边30米DEM.mat")))
        self.dem = np.asarray(raw["dem"], dtype=float)
        self.tr = np.asarray(raw["transform"]).ravel()
        self.nodata = float(raw["nodata"].item())
        self.lon0 = float(self.nodes.lon.iloc[0])
        self.lat0 = float(self.nodes.lat.iloc[0])
        self.mx = float(local_xy(self.lon0 + 1, self.lat0, self.lon0, self.lat0)[0])
        self.my = float(local_xy(self.lon0, self.lat0 + 1, self.lon0, self.lat0)[1])
        self.xyz = np.asarray(self.nodes[["x_m", "y_m", "operation_m"]], dtype=float)
        self.gateway = np.array([0.0, 0.0, float(self.nodes.ground_m.iloc[0]) + 20.0])
        self.plan = plan
        self.routes = list(plan.get("routes", []))
        self.relays = list(plan.get("relays", []))
        self.relay_by_slot = {int(x["slot"]): x for x in self.relays}
        self.catinfo = {c: g.iloc[0].to_dict() for c, g in self.boxes.groupby("category")}
        self.rows = []
        self.failures = []
        self.recomputed_routes = {}
        self.recomputed_relays = {}
        self.comm_certificates = []

    def add(self, name, passed, value=None, limit=None, note=""):
        passed = bool(passed)
        self.rows.append({"check": name, "passed": passed, "value": value,
                          "limit": limit, "note": note})
        if not passed:
            self.failures.append({"check": name, "value": value, "limit": limit,
                                  "note": note})
        return passed

    def raster(self, p):
        dx, _, left, _, dy, top = self.tr
        return np.array([(self.lon0 + p[0] / self.mx - left) / dx,
                         (self.lat0 + p[1] / self.my - top) / dy, p[2]], float)

    def ground(self, x, y):
        c, r, _ = self.raster(np.array([x, y, 0.0]))
        ci, ri = int(math.floor(c)), int(math.floor(r))
        if 0 <= ri < self.dem.shape[0] and 0 <= ci < self.dem.shape[1]:
            z = float(self.dem[ri, ci])
            if np.isfinite(z) and z != self.nodata:
                return z
        return None

    def line_clear(self, a, b):
        return bool(sweep_clear(self.raster(np.asarray(a, float)),
                                self.raster(np.asarray(b, float)),
                                self.raster(np.asarray(b, float)),
                                self.dem, self.nodata))

    def link_margin(self, a, b, limit):
        """Worst endpoint distance plus exact swept DEM test for a moving link."""
        a = np.asarray(a, float); b = np.asarray(b, float)
        d = max(float(np.linalg.norm(a - self.gateway)),
                float(np.linalg.norm(b - self.gateway)))
        # This helper is only used for gateway links.  The caller supplies a
        # separate endpoint q for relay links through link_margin_q.
        return self.link_margin_q(a, b, self.gateway, limit)

    def link_margin_q(self, a, b, q, limit):
        a = np.asarray(a, float); b = np.asarray(b, float); q = np.asarray(q, float)
        d = max(float(np.linalg.norm(a - q)), float(np.linalg.norm(b - q)))
        fspl = 32.45 + 20.0 * math.log10(2400.0) + 20.0 * math.log10(max(d, 1e-9) / 1000.0)
        clear = bool(sweep_clear(self.raster(a), self.raster(b), self.raster(q),
                                 self.dem, self.nodata))
        return float(limit - fspl - (0.0 if clear else 10.0)), clear

    def relay_geometry(self, r):
        posd = r["position"]
        x, y = float(posd["x"]), float(posd["y"])
        z = float(posd["z"])
        ground = self.ground(x, y)
        if ground is None:
            return None
        height = z - ground
        p = np.array([x, y, z], float)
        p0 = self.xyz[0]
        cells = supercover(*self.raster(p0)[:2], *self.raster(p)[:2], self.dem.shape)
        terrain = max(float(self.dem[rr, cc]) for rr, cc in cells)
        H = max(terrain + 50.0, float(self.xyz[0, 2]), z)
        up = H - float(self.xyz[0, 2]); down = H - z
        dist = float(math.hypot(x, y))
        out_s = up / 4.0 + dist / 15.0 + down / 3.0
        back_s = down / 4.0 + dist / 15.0 + up / 3.0
        travel = 1.15 * (2.0 * dist / 15.0) / 3600.0
        travel += 23.5 * 9.81 * (up + down) / (0.72 * 3.6e6)
        e0 = travel + 1.1 * 30.0 / 3600.0
        # Fixed gateway-to-relay backhaul is part of the continuous link rule.
        back_margin, back_clear = self.link_margin_q(p, p, self.gateway, 126.0)
        return dict(x=x, y=y, z=z, ground=ground, height=height, cruise=H,
                    out_s=out_s, back_s=back_s, travel_kwh=travel, e0=e0,
                    dmax=(2.56 - e0) * 3600.0 / 1.1,
                    energy=e0 + 1.1 * float(r["duration"]) / 3600.0,
                    back_margin=back_margin, back_clear=back_clear)

    def route_stages(self, r):
        """Reconstruct all flight and delivery phases from raw node geometry."""
        v = self.vs[r["vehicle"]]
        counts = {str(k): int(val) for k, val in r["counts"].items()}
        mass = sum(float(self.catinfo[c]["mass"]) * n for c, n in counts.items())
        nbox = sum(counts.values())
        t = float(r["start"]) + v.prep + v.load * nbox
        q = mass
        stages = []
        ids = [0] + [int(z[1:]) for z in r["zones"]] + [0]
        for h, (i, j) in enumerate(zip(ids, ids[1:])):
            g = self.geos[i, j]
            a0 = self.xyz[i].copy(); a1 = a0.copy(); a1[2] = g["cruise"]
            b0 = self.xyz[j].copy(); b1 = b0.copy(); b1[2] = g["cruise"]
            phases = [("爬升", a0, a1, float(g["up"]) / v.up),
                      ("巡航", a1, b1, float(g["distance"]) / v.speed),
                      ("下降", b1, b0, float(g["down"]) / v.down)]
            for phase, a, b, dt in phases:
                if dt <= 1e-10:
                    continue
                stages.append(dict(phase=phase, t0=t, t1=t + dt,
                                   a=a.tolist(), b=b.tolist()))
                t += dt
            if j:
                nd = int(sum(r["deliveries"][h]["counts"].values()))
                dt = v.handoff0 + nd * v.handoff1
                p = self.xyz[j].tolist()
                stages.append(dict(phase="物资投送", t0=t, t1=t + dt, a=p, b=p))
                t += dt
                for c, n in r["deliveries"][h]["counts"].items():
                    q -= float(self.catinfo[c]["mass"]) * int(n)
        return stages, mass, nbox, t

    @staticmethod
    def position(stage, t):
        t0, t1 = float(stage["t0"]), float(stage["t1"])
        a, b = np.asarray(stage["a"], float), np.asarray(stage["b"], float)
        if t1 <= t0 + 1e-12:
            return a
        u = min(1.0, max(0.0, (float(t) - t0) / (t1 - t0)))
        return a + u * (b - a)

    def communication(self, r, stages):
        # The MILP stores need/link timestamps relative to a route's own
        # start, while stage reconstruction below uses global time.
        links = []
        for x in r.get("links", []):
            y = dict(x)
            y["t0"] = float(x["t0"]) + float(r["start"])
            y["t1"] = float(x["t1"]) + float(r["start"])
            links.append(y)
        links.sort(key=lambda x: float(x["t0"]))
        route_ok = True; interval_count = 0; relay_count = 0
        for st in stages:
            t0, t1 = float(st["t0"]), float(st["t1"])
            cuts = [t0, t1]
            for lk in links:
                a, b = float(lk["t0"]), float(lk["t1"])
                if b > t0 + TOL and a < t1 - TOL:
                    cuts += [max(t0, a), min(t1, b)]
            cuts = sorted(set(round(x, 9) for x in cuts))
            for x0, x1 in zip(cuts, cuts[1:]):
                if x1 - x0 <= 1e-8:
                    continue
                p0 = self.position(st, x0); p1 = self.position(st, x1)
                md, _ = self.link_margin_q(p0, p1, self.gateway, 122.0)
                interval_count += 1
                if md >= -1e-6:
                    self.comm_certificates.append(dict(route_id=r['route_id'],phase=st['phase'],t0=x0,t1=x1,
                                                       provider='G01',lower_margin_dB=md))
                    continue  # direct is always preferred when available
                mid = (x0 + x1) / 2.0
                cand = [lk for lk in links if float(lk["t0"]) <= mid + TOL and
                        float(lk["t1"]) >= mid - TOL]
                if not cand:
                    route_ok = False
                    self.add(f"通信/{r['route_id']}/{x0:.3f}-{x1:.3f}", False,
                             note="直连不可用且没有指定中继覆盖")
                    continue
                lk = cand[0]
                slot = int(lk["relay_slot"]); relay = self.relay_by_slot.get(slot)
                if relay is None:
                    route_ok = False
                    self.add(f"通信/{r['route_id']}/{x0:.3f}-{x1:.3f}", False,
                             note=f"中继槽位 {slot} 不存在")
                    continue
                rg = self.relay_geometry(relay)
                q = np.array([rg["x"], rg["y"], rg["z"]])
                access, _ = self.link_margin_q(p0, p1, q, 116.0)
                service = float(relay["alpha"]) <= x0 + TOL and float(relay["beta"]) >= x1 - TOL
                back = rg["back_margin"] >= -1e-6
                good = access >= -1e-6 and service and back
                self.comm_certificates.append(dict(route_id=r['route_id'],phase=st['phase'],t0=x0,t1=x1,
                                                   provider=relay['relay_id'],lower_margin_dB=min(access,rg['back_margin'])))
                route_ok &= good; relay_count += 1
                self.add(f"通信/{r['route_id']}/{x0:.3f}-{x1:.3f}", good,
                         value={"direct_margin": md, "access_margin": access,
                                "backhaul_margin": rg["back_margin"], "slot": slot},
                         note="直连不可用时的同一中继接入+回传证书")
        self.add(f"通信连续性/{r['route_id']}", route_ok,
                 value={"intervals": interval_count, "relay_intervals": relay_count})
        return route_ok

    def verify_routes(self):
        expected_box = set(self.boxes["box"].astype(str))
        assigned = list(self.plan.get("boxes", []))
        self.add("运输架次非空", len(self.routes) > 0, value=len(self.routes))
        all_ids = [str(b.get("box")) for b in assigned]
        self.add("货箱总数", len(assigned) == len(expected_box), value=len(assigned), limit=len(expected_box))
        self.add("货箱编号唯一", len(all_ids) == len(set(all_ids)) == len(expected_box), value=len(set(all_ids)))
        self.add("货箱集合一致", set(all_ids) == expected_box,
                 note=f"缺失={sorted(expected_box-set(all_ids))[:5]},多余={sorted(set(all_ids)-expected_box)[:5]}")
        byroute = defaultdict(list)
        for b in assigned: byroute[str(b.get("route_id"))].append(b)
        fleet_uav = {"A": [f"U{i:02d}" for i in range(1, 5)],
                     "B": ["U05", "U06"], "C": ["U07", "U08"]}
        fleet_bat = {"A": [f"A-BAT-{i:02d}" for i in range(1, 7)],
                     "B": [f"B-BAT-{i:02d}" for i in range(1, 5)],
                     "C": [f"C-BAT-{i:02d}" for i in range(1, 5)]}
        for r in self.routes:
            rid = str(r["route_id"]); g = str(r["vehicle"]); v = self.vs[g]
            stages, mass, nbox, finish_recalc = self.route_stages(r)
            counts = {str(k): int(val) for k, val in r["counts"].items()}
            dcounts=defaultdict(int)
            for d in r['deliveries']:
                for cat,num in d['counts'].items():
                    dcounts[cat]+=num
                    self.add(f"路线/{rid}/目的地/{cat}", cat.split('|')[0]==d['zone'] and int(num)==num and num>0)
            self.add(f"路线/{rid}/装卸组批一致", dict(dcounts)==counts and len(r['zones'])==len(set(r['zones'])))
            vol = sum(float(self.catinfo[c]["volume"]) * n for c, n in counts.items())
            energy = 0.0; q = mass; segs = []; offsets = {}
            elapsed = v.prep + v.load * nbox
            ids = [0] + [int(z[1:]) for z in r["zones"]] + [0]
            for h, (i, j) in enumerate(zip(ids, ids[1:])):
                s = seg(v, self.geos[i, j], q); energy += s["energy"]; segs.append(s)
                elapsed += s["time"]
                if j:
                    elapsed += v.handoff0 + sum(r["deliveries"][h]["counts"].values()) * v.handoff1
                    for c, n in r["deliveries"][h]["counts"].items():
                        offsets[c] = elapsed
                        q -= float(self.catinfo[c]["mass"]) * int(n)
            prep = v.prep + v.load * nbox
            capacity_ok = mass <= v.capacity + ETOL and vol <= v.volume + ETOL
            energy_ok = energy <= 0.8 * v.battery + ETOL
            temporal_ok = abs(float(r["finish"]) - finish_recalc) <= TOL
            timing_ok = abs(float(r["takeoff"]) - (float(r["start"]) + prep)) <= TOL
            charge_re = charge(v, 1.0 - energy / v.battery)
            charge_ok = abs(float(r["charge_s"]) - charge_re) <= TOL
            self.add(f"路线/{rid}/载荷体积", capacity_ok,
                     value={"mass": mass, "volume": vol},
                     limit={"mass": v.capacity, "volume": v.volume})
            self.add(f"路线/{rid}/返航能量余量", energy_ok,
                     value=energy, limit=0.8 * v.battery)
            self.add(f"路线/{rid}/能耗重算", abs(energy-float(r["energy"])) <= ETOL,
                     value=energy, limit=float(r["energy"]))
            self.add(f"路线/{rid}/SOC重算", abs(1-energy/v.battery-float(r["soc"])) <= ETOL)
            self.add(f"路线/{rid}/卸载偏移重算", set(offsets) == set(r["offsets"]) and
                     all(abs(offsets[c]-float(r["offsets"][c])) <= TOL for c in offsets))
            self.add(f"路线/{rid}/非负开始时刻", float(r["start"]) >= -TOL)
            self.add(f"路线/{rid}/时间重算", temporal_ok,
                     value={"stored_finish": r["finish"], "recomputed_finish": finish_recalc})
            self.add(f"路线/{rid}/起飞准备", timing_ok,
                     value={"stored": r["takeoff"], "recomputed": float(r["start"]) + prep})
            self.add(f"路线/{rid}/充电时间", charge_ok,
                     value={"stored": r["charge_s"], "recomputed": charge_re})
            self.add(f"路线/{rid}/充电完成重算", abs(float(r["recharge"])-finish_recalc-charge_re) <= TOL)
            self.recomputed_routes[rid] = dict(start=float(r["start"]), finish=finish_recalc,
                                               recharge=finish_recalc+charge_re, energy=energy,
                                               offsets=offsets)
            self.add(f"路线/{rid}/无人机编号", str(r.get("uav")) in fleet_uav[g], value=r.get("uav"))
            self.add(f"路线/{rid}/电池编号", str(r.get("battery_id")) in fleet_bat[g], value=r.get("battery_id"))
            self.communication(r, stages)
            # Count consistency against the independently assigned box list.
            got = defaultdict(int)
            for b in byroute.get(rid, []): got[str(b["zone"])+"|"+str(b["kind"])] += 1
            self.add(f"路线/{rid}/逐箱组批一致", dict(got) == counts,
                     value=dict(got), limit=counts)
        for g, allowed_u in fleet_uav.items():
            rr = [r for r in self.routes if r["vehicle"] == g]
            self.add(f"机型{g}/实体数量", len(set(str(r["uav"]) for r in rr)) <= len(allowed_u),
                     value=len(set(str(r["uav"]) for r in rr)), limit=len(allowed_u))
            for u in allowed_u:
                items = [dict(start=r["start"], end=self.recomputed_routes[r["route_id"]]["finish"], route_id=r["route_id"])
                         for r in rr if r.get("uav") == u]
                self.add(f"资源/{u}/运输机不重叠", not pairwise_conflicts(items, "start", "end"),
                         value=len(pairwise_conflicts(items, "start", "end")))
        for g, allowed_b in fleet_bat.items():
            rr = [r for r in self.routes if r["vehicle"] == g]
            self.add(f"机型{g}/共享电池类型", all(str(r["battery_id"]) in allowed_b for r in rr))
            for b in allowed_b:
                items = [dict(start=r["start"], end=self.recomputed_routes[r["route_id"]]["recharge"], route_id=r["route_id"])
                         for r in rr if r.get("battery_id") == b]
                self.add(f"资源/{b}/电池占用不重叠", not pairwise_conflicts(items, "start", "end"),
                         value=len(pairwise_conflicts(items, "start", "end")))

    def verify_boxes(self):
        raw = self.boxes.set_index("box")
        for b in self.plan.get("boxes", []):
            bid = str(b.get("box"))
            if bid not in raw.index: continue
            row = raw.loc[bid]
            self.add(f"货箱/{bid}/原始属性", str(b["zone"]) == str(row.zone) and str(b["kind"]) == str(row.kind)
                     and abs(float(b["mass"])-float(row.mass)) < ETOL
                     and abs(float(b["volume"])-float(row.volume)) < ETOL)
            deadline = float(row["deadline"])
            delivery = float(b["delivery"])
            if bool(row["hard"]):
                self.add(f"时限/{bid}", delivery <= deadline + TOL,
                         value=delivery, limit=deadline)
        # Every category's independently sorted slot delivery agrees with the
        # actual route offset, without trusting the solver's box order.
        bycat = defaultdict(list)
        for r in self.routes:
            for c, n in r["counts"].items():
                t = float(r["start"]) + self.recomputed_routes[r["route_id"]]["offsets"][c]
                bycat[c] += [(t, r["route_id"])] * int(n)
        got = defaultdict(list)
        for b in self.plan.get("boxes", []): got[str(b["category"])].append((float(b["delivery"]), b["route_id"]))
        for c, group in self.boxes.groupby("category"):
            exp = sorted(bycat[c]); actual = sorted(got[c])
            self.add(f"逐箱交付/{c}/时刻一致", len(exp) == len(actual) and
                     all(abs(x[0]-y[0]) <= TOL and x[1] == y[1] for x, y in zip(exp, actual)),
                     value={"expected": exp[:2], "actual": actual[:2]})

    def verify_relays(self):
        self.add("中继架次非空", len(self.relays) > 0, value=len(self.relays))
        self.add("中继槽位唯一", len(self.relays) == len(self.relay_by_slot))
        self.add("中继无人机库存", len(set(r["uav"] for r in self.relays)) <= 2,
                 value=sorted(set(r["uav"] for r in self.relays)), limit=2)
        self.add("中继能源组件库存", len(set(r["component"] for r in self.relays)) <= 6,
                 value=len(set(r["component"] for r in self.relays)), limit=6)
        for r in self.relays:
            rid = str(r["relay_id"]); rg = self.relay_geometry(r)
            if rg is None:
                self.add(f"中继/{rid}/位置", False, note="位置不在DEM有效范围")
                continue
            self.add(f"中继/{rid}/离地高度", rg["height"] <= 300.0 + TOL,
                     value=rg["height"], limit=300.0)
            self.add(f"中继/{rid}/位置与编号", 0 < rg["height"] <= 300.0 + TOL
                     and r["uav"] in ("R01", "R02")
                     and r["component"] in [f"R-EC-{i:02d}" for i in range(1, 7)]
                     and float(r["start"]) >= -TOL
                     and abs(float(r["position"]["lon"])-(self.lon0+rg["x"]/self.mx)) < 1e-9
                     and abs(float(r["position"]["lat"])-(self.lat0+rg["y"]/self.my)) < 1e-9)
            self.add(f"中继/{rid}/回传链路", rg["back_margin"] >= -1e-6,
                     value=rg["back_margin"], limit=0.0)
            expected = {
                "takeoff": float(r["start"]) + 180.0,
                "arrival": float(r["start"]) + 180.0 + rg["out_s"],
                "alpha": float(r["start"]) + 180.0 + rg["out_s"] + 30.0,
                "finish": float(r["start"]) + 180.0 + rg["out_s"] + 30.0 + float(r["duration"]) + rg["back_s"],
                "energy": rg["energy"],
            }
            for k in ("takeoff", "arrival", "alpha", "finish"):
                self.add(f"中继/{rid}/{k}重算", abs(float(r[k])-expected[k]) <= TOL,
                         value={"stored": r[k], "recomputed": expected[k]})
            self.add(f"中继/{rid}/服务能量", abs(float(r["energy"])-rg["energy"]) <= ETOL,
                     value=float(r["energy"]), limit=rg["energy"])
            self.add(f"中继/{rid}/返航能量余量", rg["energy"] <= 2.56 + ETOL,
                     value=rg["energy"], limit=2.56)
            soc = 1.0 - rg["energy"] / 3.2
            ch = 1800.0 * (0.65 * (0.9 - soc) / 0.9 + 0.35) if soc < 0.9 else 1800.0 * 0.35 * (1.0 - soc) / 0.1
            self.add(f"中继/{rid}/充电时间", abs(float(r["charge_s"])-ch) <= TOL,
                     value={"stored": r["charge_s"], "recomputed": ch})
            self.add(f"中继/{rid}/服务结束", abs(float(r["beta"])-expected["alpha"]-float(r["duration"])) <= TOL)
            self.add(f"中继/{rid}/SOC", abs(float(r["soc"])-soc) <= ETOL)
            self.add(f"中继/{rid}/资源完成", abs(float(r["recharge"])-expected["finish"]-ch) <= TOL
                     and abs(float(r["body_ready"])-expected["finish"]-300) <= TOL)
            self.recomputed_relays[rid] = dict(energy=rg["energy"], finish=expected["finish"],
                                               recharge=expected["finish"]+ch, body_ready=expected["finish"]+300)
        for u in ("R01", "R02"):
            items = [dict(start=r["start"], end=self.recomputed_relays[r["relay_id"]]["body_ready"], relay_id=r["relay_id"])
                     for r in self.relays if r.get("uav") == u]
            self.add(f"资源/{u}/中继机体不重叠", not pairwise_conflicts(items, "start", "end"),
                     value=len(pairwise_conflicts(items, "start", "end")))
        for comp in sorted(set(str(r["component"]) for r in self.relays)):
            items = [dict(start=r["start"], end=self.recomputed_relays[r["relay_id"]]["recharge"], relay_id=r["relay_id"])
                     for r in self.relays if r.get("component") == comp]
            self.add(f"资源/{comp}/能源组件不重叠", not pairwise_conflicts(items, "start", "end"),
                     value=len(pairwise_conflicts(items, "start", "end")))

    def finish(self):
        # Recompute objective from raw data, including all boxes.
        raw = self.boxes.set_index("box")
        et = sum(r["energy"] for r in self.recomputed_routes.values())
        er = sum(r["energy"] for r in self.recomputed_relays.values())
        c = max([r["finish"] for r in self.recomputed_routes.values()] +
                [r["finish"] for r in self.recomputed_relays.values()])
        denom = float(self.boxes.loc[~self.boxes.hard, "priority"].sum())
        late = 0.0
        for b in self.plan.get("boxes", []):
            row = raw.loc[str(b["box"])]
            if not bool(row["hard"]): late += float(row["priority"]) * max(0.0, float(b["delivery"]) - float(row["expected"]))
        L = late / denom
        calc = [len(self.routes) + len(self.relays), et + er, c, L]
        stored = [float(x) for x in self.plan.get("objective", [])]
        self.add("目标值重算", len(stored) == 4 and all(abs(a-b) <= 2e-4 for a,b in zip(calc, stored)),
                 value={"stored": stored, "recomputed": calc})
        passed = len(self.failures) == 0
        result = {"status": "PASS" if passed else "FAIL", "passed": passed,
                  "plan": str(PLAN_PATH), "routes": len(self.routes), "relays": len(self.relays),
                  "boxes": len(self.plan.get("boxes", [])), "objective_stored": stored,
                  "objective_recomputed": calc, "failure_count": len(self.failures),
                  "failures": self.failures, "checks": self.rows,
                  "tolerance": {"time_s": TOL, "energy_kWh": ETOL},
                  "certified_intervals": len(self.comm_certificates),
                  "minimum_certificate_lower_margin_dB": min(x['lower_margin_dB'] for x in self.comm_certificates),
                  "communication_scope": "每个爬升、巡航、下降和物资投送阶段按DEM扫掠证书分段核验；直连优先，直连失败时核验同一中继的接入与回传。"}
        return result


def main():
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    v = Verifier(plan)
    v.verify_routes(); v.verify_boxes(); v.verify_relays()
    result = v.finish()
    OUT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    pd.DataFrame(v.rows).to_csv(DETAIL_PATH, index=False, encoding="utf-8-sig")
    pd.DataFrame(v.comm_certificates).to_csv(HERE/'子问题二/全区间通信证书.csv',index=False,encoding='utf-8-sig')
    print(json.dumps({k: result[k] for k in ("status", "passed", "failure_count", "objective_stored", "objective_recomputed")}, ensure_ascii=False))
    if not result["passed"]:
        for x in result["failures"][:25]: print("FAIL", x)
        raise SystemExit(2)


if __name__ == "__main__":
    main()
