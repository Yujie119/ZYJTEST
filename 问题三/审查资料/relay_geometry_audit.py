"""Read-only relay-flight audit; writes JSON/Markdown only beside this script."""
from __future__ import annotations
import os
os.environ["MKL_THREADING_LAYER"] = "SEQUENTIAL"
for _name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_name] = "1"
import hashlib
import itertools
import json
import math
from pathlib import Path
import numpy as np
from openpyxl import load_workbook
from scipy.io import loadmat

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[1]
DATA = ROOT / "D题/数据/无人机应急物资运输基础数据"


def rows(path):
    book = load_workbook(path, data_only=True, read_only=True)
    result = list(book.worksheets[0].values)
    book.close()
    return result


class Inputs:
    def __init__(self):
        rr = rows(DATA / "中继无人机数据.xlsx")
        self.relay = dict(zip(rr[1], rr[2]))
        self.link = {(r[0], r[1]): float(r[4]) for r in rows(DATA / "通信链路参数.xlsx")
                     if r[0] not in (None, "通信系统与端点参数", "参数类别")}
        self.nodes = [dict(zone=r[0], lon=float(r[2]), lat=float(r[3]), ground=float(r[4]))
                      for r in rows(DATA / "调度中心与服务区.xlsx") if isinstance(r[0], str)
                      and (r[0] == "O01" or (r[0].startswith("S") and r[0][1:].isdigit()))]
        depot = self.nodes[0]
        self.lon0, self.lat0 = depot["lon"], depot["lat"]
        phi = math.radians(self.lat0)
        e2, earth_a = 6.6943799901413165e-3, 6378137.0
        n = earth_a / math.sqrt(1 - e2 * math.sin(phi) ** 2)
        m = earth_a * (1 - e2) / (1 - e2 * math.sin(phi) ** 2) ** 1.5
        self.mx, self.my = math.pi / 180 * n * math.cos(phi), math.pi / 180 * m
        self.dem_path = next((ROOT / "D题/数据").rglob("镇龙乡及周边30米DEM.mat"))
        raw = loadmat(self.dem_path)
        self.dem = np.asarray(raw["dem"], float)
        self.transform = np.asarray(raw["transform"]).ravel()
        self.nodata = float(np.asarray(raw["nodata"]).item())
        self.depot = np.array([0.0, 0.0, depot["ground"]])
        self.gateway = self.depot.copy()
        self.gateway[2] += self.link["固定网关 G01", "天线离地高度（m）"]
        for node in self.nodes:
            node["xyz"] = np.array([(node["lon"] - self.lon0) * self.mx,
                                    (node["lat"] - self.lat0) * self.my,
                                    node["ground"] + (0 if node["zone"] == "O01" else 30)])

    def raster(self, point):
        dx, _, left, _, dy, top = self.transform
        return np.array([(self.lon0 + point[0] / self.mx - left) / dx,
                         (self.lat0 + point[1] / self.my - top) / dy, point[2]])

    def cells(self, a, b):
        """Closed touched cells and their line-parameter intervals, independently."""
        ra, rb = self.raster(a), self.raster(b)
        boundaries = [0.0, 1.0]
        for axis in (0, 1):
            p, q = ra[axis], rb[axis]
            if abs(q - p) > 1e-14:
                boundaries.extend((k - p) / (q - p)
                                  for k in range(math.floor(min(p, q)) + 1,
                                                 math.ceil(max(p, q))))
        ts = np.unique(np.clip(boundaries, 0, 1))
        result = {}

        def put(t0, t1, probe):
            p = ra + (rb - ra) * probe
            for epsx, epsy in itertools.product((-1e-9, 0.0, 1e-9), repeat=2):
                col, row = math.floor(p[0] + epsx), math.floor(p[1] + epsy)
                if not (0 <= row < self.dem.shape[0] and 0 <= col < self.dem.shape[1]):
                    raise ValueError("Tested line leaves DEM")
                lo, hi = result.get((row, col), (1.0, 0.0))
                result[row, col] = min(lo, t0), max(hi, t1)

        for t in ts:
            put(t, t, t)
        for t0, t1 in zip(ts, ts[1:]):
            put(t0, t1, (t0 + t1) / 2)
        return result

    def terrain_max(self, a, b):
        values = [float(self.dem[row, col]) for row, col in self.cells(a, b)]
        if any(not math.isfinite(v) or v == self.nodata for v in values):
            raise ValueError("Unknown DEM cell in path")
        return max(values)

    def threshold(self, one, two):
        value = self.link
        threshold = value["接收参数", "接收灵敏度（dBm）"] + value["接收参数", "衰落裕量（dB）"]
        gains = value[one, "天线增益（dBi）"] + value[two, "天线增益（dBi）"]
        sys_loss = value["传播参数", "系统损耗（dB）"]
        return min(value[one, "发射功率（dBm）"], value[two, "发射功率（dBm）"]) + gains - sys_loss - threshold

    def point_link(self, a, b, threshold):
        """Independent point LOS; no production communication-cache labels."""
        distance = float(np.linalg.norm(a - b))
        min_clearance = math.inf
        for (row, col), (lo, hi) in self.cells(a, b).items():
            ground = float(self.dem[row, col])
            if not math.isfinite(ground) or ground == self.nodata:
                raise ValueError("Unknown DEM cell in LOS")
            minimum_z = min(a[2] + (b[2] - a[2]) * lo, a[2] + (b[2] - a[2]) * hi)
            min_clearance = min(min_clearance, minimum_z - ground)
        blocked = min_clearance <= 1e-6
        loss = 32.45 + 20 * math.log10(self.link["传播参数", "载波频率（MHz）"])
        loss += 20 * math.log10(max(distance, 1e-9) / 1000)
        loss += self.link["传播参数", "地形遮挡附加损耗（dB）"] * blocked
        return dict(margin_db=float(threshold - loss), blocked=bool(blocked),
                    distance_m=distance, minimum_clearance_m=float(min_clearance))


def signed_vertical(z0, z1, up_speed, down_speed):
    climb, descent = max(0.0, z1 - z0), max(0.0, z0 - z1)
    return dict(from_m=float(z0), to_m=float(z1), climb_m=float(climb), descent_m=float(descent),
                seconds=float(climb / up_speed + descent / down_speed))


def path_metrics(inp, xyz, level):
    r = inp.relay
    speed = r["计划巡航速度（m/s）"]
    up, down = r["最大爬升速度（m/s）"], r["最大下降速度（m/s）"]
    distance = float(np.linalg.norm(xyz[:2]))
    vertical = [signed_vertical(inp.depot[2], level, up, down),
                signed_vertical(level, xyz[2], up, down),
                signed_vertical(xyz[2], level, up, down),
                signed_vertical(level, inp.depot[2], up, down)]
    horizontal_seconds = distance / speed
    climb = sum(v["climb_m"] for v in vertical)
    descent = sum(v["descent_m"] for v in vertical)
    horizontal_energy = r["巡航功率（kW）"] * 2 * horizontal_seconds / 3600
    climb_energy = r["计划起飞总质量（kg）"] * 9.81 * climb / (r["爬升能耗效率"] * 3.6e6)
    return dict(horizontal_altitude_m=float(level), horizontal_oneway_m=distance,
                out_s=sum(v["seconds"] for v in vertical[:2]) + horizontal_seconds,
                back_s=sum(v["seconds"] for v in vertical[2:]) + horizontal_seconds,
                climb_roundtrip_m=climb, descent_roundtrip_m=descent,
                horizontal_energy_kwh=horizontal_energy, climb_energy_kwh=climb_energy,
                travel_energy_kwh=horizontal_energy + climb_energy,
                signed_vertical_segments=vertical)


def compare(inp, q):
    xyz = np.array([q["x"], q["y"], q["z"]], float)
    h0 = inp.terrain_max(inp.depot, xyz) + 50
    a = path_metrics(inp, xyz, max(h0, float(inp.depot[2]), float(xyz[2])))
    b = path_metrics(inp, xyz, h0)
    keys = ("out_s", "back_s", "climb_roundtrip_m", "descent_roundtrip_m", "travel_energy_kwh")
    return dict(qid=q.get("qid"), xyz_m=xyz.tolist(), height_agl_m=q["height"],
                original_cruise_h0_m=float(h0), current_raise_m=float(a["horizontal_altitude_m"] - h0),
                A=a, B=b, A_minus_B={k: a[k] - b[k] for k in keys},
                C_strict_admissible=bool(xyz[2] <= h0 + 1e-9 and inp.depot[2] <= h0 + 1e-9),
                equivalence_endpoint_condition=bool(h0 >= min(inp.depot[2], xyz[2])), point=xyz)


def make_markdown(result):
    lines = ["# 中继航段解释的原DEM量化核查", "",
             "本文件由同目录脚本读取原始工作簿、原DEM及当前最终方案自动生成；未修改生产代码或结果。", "",
             "## 三种解释及等价关系", "",
             "A：水平巡航面取 max(H0,zO,zq)。B：水平巡航面固定为题给 H0=max(沿线DEM)+50 m，在O01与悬停点分别按有符号高度变化执行垂直阶段；高位悬停点处为末端爬升，返程先下降。C：固定H0且要求两端均不高于H0，直接排除高位悬停候选。", "",
             "设巡航面为H，完整往返的爬升与下降总高度均为", "",
             "$$S(H)=|H-z_O|+|H-z_q|.$$", "",
             r"往返垂直总时间为 $S(H)(1/v^\uparrow+1/v^\downarrow)$，势能附加能耗为 $m g S(H)/(\eta\,3.6\times10^6)$；水平距离与速度相同。", "",
             r"当 $H_0\ge\min(z_O,z_q)$ 时，$S(H_0)=S(\max(H_0,z_O,z_q))$。本场景O01低于全部候选的H0，因此A/B不仅往返总时间、总能耗相等，而且去程和返程各自的时间也相等。若H0低于两个端点则此等价不成立，不能无条件推广。", "",
             "## 最终四中继架次", "",
             "| 架次 | H0/m | 悬停海拔/m | A提高巡航面/m | A去程/s | B去程/s | A返程/s | B返程/s | A/B飞行能耗差/kWh | 严格C |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for row in result["final_relays"]:
        a, b = row["A"], row["B"]
        lines.append(f'| {row["relay_id"]} | {row["original_cruise_h0_m"]:.6f} | {row["xyz_m"][2]:.6f} | {row["current_raise_m"]:.6f} | {a["out_s"]:.9f} | {b["out_s"]:.9f} | {a["back_s"]:.9f} | {b["back_s"]:.9f} | {row["A_minus_B"]["travel_energy_kwh"]:.3e} | {"通过" if row["C_strict_admissible"] else "排除"} |')
    lines += ["", "A/B只改变中继赴返的三维路径形状。悬停位置、到位/建链/服务/返场时刻、耗能、SOC与充电时间保持相同。题目要求连续通信的直接对象是运输无人机，没有要求中继赴返飞行全程也保持网关链路；因此在题给定功率与势能能耗模型内，这种路径差异不改变运输通信保障或四项目标。不能声称A/B能耗必然不同，也不能仅凭提高巡航面就判定现方案数值无效。", "",
              "B允许高端点采用末端爬升，属于对原题“爬升—巡航—下降”阶段措辞的有符号解释；C则严格限定只能末端下降。题意解释仍需在正文说明，这个数值等价试验本身不证明原题明确指定了哪种解释。", "",
              "## 当前24个候选的严格C检查", "",
              f'严格C保留 {result["strict_C"]["candidate_count"]}/{result["candidate_count"]} 个候选：{", ".join(result["strict_C"]["candidate_ids"]) or "无"}。', "",
              "逐点接入与回传使用原始通信表和DEM重新计算；服务区按地面海拔+30 m。此处只核查固定服务点，不能代替飞行全过程或联合资源排程。", "",
              "| 服务区 | 直连裕量/dB | 严格C可用中继候选 | 服务点可保障 |",
              "|---|---:|---|---|"]
    for row in result["strict_C"]["service_nodes"]:
        lines.append(f'| {row["zone"]} | {row["direct"]["margin_db"]:.6f} | {", ".join(row["available_relay_candidates"]) or "无"} | {"是" if row["covered"] else "否"} |')
    failures = result["strict_C"]["uncovered_service_nodes"]
    lines += ["", f'严格C当前候选集无法保障的服务节点：{", ".join(failures) or "无"}。', "",
              "这仅说明现有24点中满足C条件的子集，不证明连续DEM空间中不存在其他低位或不同水平位置的可行中继。没有重求联合调度，也没有据此声称全题不可行。", "",
              "## 复现", "", chr(96) * 3 + "powershell",
              "& 'E:\\tool\\anaconda3\\python.exe' -X utf8 '问题三\\审查资料\\relay_geometry_audit.py'",
              chr(96) * 3, "",
              "原始输入、候选与方案SHA-256及所有24点明细见同名JSON。数值等价容差仅用于浮点算术核对；通信仍按原题32.45常数、双向门限和地形附加损耗计算。", ""]
    return "\n".join(lines)


def main():
    inp = Inputs()
    final_path = ROOT / "问题三/子问题二/最终方案.json"
    candidates_path = ROOT / "问题三/缓存/中继候选位置.json"
    plan = json.loads(final_path.read_text(encoding="utf-8"))
    candidates = json.loads(candidates_path.read_text(encoding="utf-8"))
    candidate_rows = [compare(inp, q) for q in candidates]
    final_rows = []
    for task in sorted(plan["relays"], key=lambda x: x["relay_id"]):
        row = compare(inp, task["position"])
        service_energy = (inp.relay["悬停功率（kW）"] + inp.relay["通信附加功率（kW）"]) * (
            inp.relay["建链时间（s）"] + task["duration"]) / 3600
        row.update(relay_id=task["relay_id"], model_energy_kwh=task["energy"],
                   A_total_energy_kwh=row["A"]["travel_energy_kwh"] + service_energy,
                   B_total_energy_kwh=row["B"]["travel_energy_kwh"] + service_energy)
        final_rows.append(row)
    eligible = [q for q in candidate_rows if q["C_strict_admissible"]]
    direct_threshold = inp.threshold("运输无人机", "固定网关 G01")
    access_threshold = inp.threshold("运输无人机", "中继接入端")
    back_threshold = inp.threshold("中继回传端", "固定网关 G01")
    service_rows = []
    for node in inp.nodes[1:]:
        direct = inp.point_link(node["xyz"], inp.gateway, direct_threshold)
        details, available = [], []
        for q in eligible:
            access = inp.point_link(node["xyz"], q["point"], access_threshold)
            back = inp.point_link(q["point"], inp.gateway, back_threshold)
            good = access["margin_db"] >= 0 and back["margin_db"] >= 0
            details.append(dict(qid=q["qid"], access=access, backhaul=back, available=good))
            if good:
                available.append(q["qid"])
        service_rows.append(dict(zone=node["zone"], xyz_m=node["xyz"].tolist(), direct=direct,
                                 relay_details=details, available_relay_candidates=available,
                                 covered=direct["margin_db"] >= 0 or bool(available)))
    maximum_differences = {key: max(abs(q["A_minus_B"][key]) for q in candidate_rows)
                           for key in candidate_rows[0]["A_minus_B"]}
    assert all(q["equivalence_endpoint_condition"] for q in candidate_rows)
    assert maximum_differences["out_s"] < 1e-9 and maximum_differences["back_s"] < 1e-9
    assert maximum_differences["travel_energy_kwh"] < 1e-12
    assert all(abs(q["A_total_energy_kwh"] - q["model_energy_kwh"]) < 1e-9 for q in final_rows)
    for q in candidate_rows + final_rows:
        q.pop("point")
    paths = [final_path, candidates_path, inp.dem_path,
             DATA / "中继无人机数据.xlsx", DATA / "通信链路参数.xlsx",
             DATA / "调度中心与服务区.xlsx"]
    result = dict(candidate_count=len(candidate_rows),
                  input_fingerprints=[dict(path=str(p), sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in paths],
                  interpretation="A: raised cruise; B: H0 cruise with signed endpoint vertical phases; C: H0 cruise and both endpoints at or below H0",
                  thresholds_db=dict(direct=direct_threshold, access=access_threshold, backhaul=back_threshold),
                  maximum_A_B_differences_all_candidates=maximum_differences,
                  all_candidates=candidate_rows, final_relays=final_rows,
                  strict_C=dict(candidate_count=len(eligible), candidate_ids=[q["qid"] for q in eligible],
                                service_nodes=service_rows,
                                uncovered_service_nodes=[r["zone"] for r in service_rows if not r["covered"]]),
                  limitations=["Existing finite candidate set only; no new coordinates or heights searched.",
                               "Service-node checks are necessary endpoint checks, not full trajectory certification.",
                               "No joint rescheduling; A/B equality concerns the stated physical model.",
                               "B changes the sign of terminal vertical phase; wording interpretation remains explicit."])
    (OUT / "relay_geometry_audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "relay_geometry_audit.md").write_text(make_markdown(result), encoding="utf-8")
    print(json.dumps(dict(status="PASS", candidate_count=len(candidate_rows),
                          maximum_A_B_differences=maximum_differences,
                          strict_C_candidates=result["strict_C"]["candidate_ids"],
                          uncovered_service_nodes=result["strict_C"]["uncovered_service_nodes"]), ensure_ascii=False))


if __name__ == "__main__":
    main()
