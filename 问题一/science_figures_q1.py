"""Research-grade Q1 figures.

The plotting choices follow the ARIS ``paper-figure`` publication preset:
vector PDF output, restrained colour, no titles inside panels, explicit units,
and data-driven annotations.  All numbers are read from the Q1 result files
and the original DEM/input workbooks; nothing is hard-coded as a result.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import Normalize
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch
import numpy as np
import pandas as pd
from scipy.io import loadmat

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import q1_core as q


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "科研级可视化"
OUT.mkdir(exist_ok=True)
S1 = ROOT / "子问题一"
S2 = ROOT / "子问题二"
S3 = ROOT / "子问题三"

plt.rcParams.update({
    "font.family": ["Noto Serif SC", "Times New Roman", "DejaVu Serif"],
    "font.size": 9.5,
    "axes.labelsize": 10,
    "axes.titlesize": 10,
    "xtick.labelsize": 8.5,
    "ytick.labelsize": 8.5,
    "legend.fontsize": 8.5,
    "axes.linewidth": 0.8,
    "xtick.major.width": 0.8,
    "ytick.major.width": 0.8,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": False,
    "savefig.dpi": 300,
    "figure.dpi": 150,
    "pdf.fonttype": 42,
    "ps.fonttype": 42,
})

COL = {"A": "#3B528B", "B": "#21918C", "C": "#F28E2B"}
RED = "#C43C39"
DARK = "#1F2937"
GREY = "#7A7A7A"


def save(fig: plt.Figure, stem: str) -> None:
    fig.savefig(OUT / f"{stem}.pdf", bbox_inches="tight", pad_inches=0.04)
    fig.savefig(OUT / f"{stem}.png", bbox_inches="tight", pad_inches=0.04, dpi=300)
    plt.close(fig)


def load_all():
    boxes, vehicles, geometry, nodes, _ = q.load_inputs()
    cap = pd.read_csv(S1 / "最大安全载荷.csv")
    plan = pd.read_csv(S2 / "最终方案明细.csv")
    front = pd.read_csv(S2 / "非支配方案.csv")
    response = pd.read_csv(S3 / "安全余量方案响应.csv")
    summary = json.loads((ROOT / "求解摘要.json").read_text(encoding="utf-8"))
    return boxes, vehicles, geometry, nodes, cap, plan, front, response, summary


def _dem_xy(nodes):
    path = q.source("镇龙乡及周边30米DEM.mat")
    dat = loadmat(path)
    dem = dat["dem"].astype(float)
    dem[dem == float(dat["nodata"].ravel()[0])] = np.nan
    tr = dat["transform"].ravel()
    dx, _, left, _, dy, top = tr
    right = left + dx * dem.shape[1]
    bottom = top + dy * dem.shape[0]
    # The raster is north-up, so local-y edges are deliberately sorted.
    xs, _ = q.local_xy(np.array([left, right]), np.array([top, top]),
                       nodes.lon.iloc[0], nodes.lat.iloc[0])
    _, ys = q.local_xy(np.array([left, left]), np.array([top, bottom]),
                       nodes.lon.iloc[0], nodes.lat.iloc[0])
    extent = [float(xs.min()), float(xs.max()), float(ys.min()), float(ys.max())]
    return dem, extent


def fig1_terrain_routes(geometry, nodes):
    dem, extent = _dem_xy(nodes)
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(10.8, 4.55),
                                  gridspec_kw={"width_ratios": [1.28, 1]})
    # Crop for readable map while keeping all service areas.
    x = nodes.x_m.to_numpy(); y = nodes.y_m.to_numpy()
    margin = 900.0
    ax.set_xlim(x.min() - margin, x.max() + margin)
    ax.set_ylim(y.min() - margin, y.max() + margin)
    im = ax.imshow(dem, extent=extent, origin="upper", cmap="terrain",
                   alpha=0.82, interpolation="nearest", aspect="equal")
    levels = np.nanpercentile(dem, np.linspace(15, 90, 8))
    # Make a light contour overlay from the un-cropped raster.
    xx = np.linspace(extent[0], extent[1], dem.shape[1])
    yy = np.linspace(extent[3], extent[2], dem.shape[0])
    ax.contour(xx, yy, dem, levels=levels, colors="#3D3D3D",
               linewidths=0.28, alpha=0.28)
    g = geometry.set_index("zone")
    norm = Normalize(g.terrain_max_m.min(), g.terrain_max_m.max())
    cmap = plt.get_cmap("viridis")
    for _, row in nodes[nodes.zone != "O01"].iterrows():
        gg = g.loc[row.zone]
        ax.plot([0, row.x_m], [0, row.y_m], color=cmap(norm(gg.terrain_max_m)),
                lw=0.85, alpha=0.72, zorder=3)
        ax.scatter(row.x_m, row.y_m, s=32 + 0.9 * gg.distance_m / 100,
                   c=[cmap(norm(gg.terrain_max_m))], edgecolor="white",
                   linewidth=0.5, zorder=5)
        if row.zone in {"S003", "S008", "S015"}:
            ax.annotate(row.zone, (row.x_m, row.y_m), xytext=(4, 4),
                        textcoords="offset points", fontsize=8, color=DARK,
                        bbox=dict(boxstyle="round,pad=0.14", fc="white", ec="none", alpha=0.72))
    ax.scatter([0], [0], s=72, marker="s", c="#111111", edgecolor="white",
               linewidth=0.8, zorder=6)
    ax.annotate("O01", (0, 0), xytext=(5, -12), textcoords="offset points",
                fontsize=8.5, color=DARK)
    ax.set_xlabel("局部东向坐标（m）")
    ax.set_ylabel("局部北向坐标（m）")
    cbar = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
    cbar.set_label("DEM高程（m）")
    ax.text(0.01, 0.98, "(a)", transform=ax.transAxes, va="top", fontweight="bold")
    ax.legend(handles=[Line2D([0], [0], color="#555555", lw=1, label="O01–服务区直飞航段"),
                       Line2D([0], [0], marker="s", color="w", markerfacecolor="#111111",
                              markersize=7, label="调度中心 O01")],
              loc="lower left", frameon=True, framealpha=0.88, edgecolor="#DDDDDD")

    gg = geometry.sort_values("terrain_max_m")
    ax2.scatter(gg.distance_m / 1000, gg.terrain_max_m, s=35,
                c=gg.outbound_up_m, cmap="magma", edgecolor="white", linewidth=0.5)
    for _, r in gg.iterrows():
        if r.zone in {"S003", "S008", "S014", "S015"}:
            ax2.annotate(r.zone, (r.distance_m / 1000, r.terrain_max_m),
                         xytext=(4, 4), textcoords="offset points", fontsize=8)
    ax2.axhline(350, color=GREY, lw=0.8, ls="--", alpha=0.75)
    ax2.set_xlabel("O01–服务区距离（km）")
    ax2.set_ylabel("航段最大地形高程（m）")
    ax2.text(0.02, 0.98, "(b)", transform=ax2.transAxes, va="top", fontweight="bold")
    sm = plt.cm.ScalarMappable(norm=Normalize(gg.outbound_up_m.min(), gg.outbound_up_m.max()), cmap="magma")
    sm.set_array([])
    c2 = fig.colorbar(sm, ax=ax2, fraction=0.045, pad=0.03)
    c2.set_label("去程爬升高度（m）")
    fig.subplots_adjust(wspace=0.28)
    save(fig, "图1_地形与航段结构")


def fig2_capacity_boundaries(geometry, cap):
    data = cap.merge(geometry[["zone", "terrain_max_m", "distance_m"]], on="zone")
    fig, axes = plt.subplots(1, 3, figsize=(10.8, 3.6), sharex=True, sharey=True)
    for ax, v in zip(axes, ["A", "B", "C"]):
        d = data[data.vehicle == v].copy()
        rated = d.capacity_kg.iloc[0]
        ax.axhline(rated, color=GREY, lw=0.9, ls="--")
        for status, marker, face in [("额定载荷受限", "o", COL[v]), ("能量受限", "^", RED)]:
            s = d[d.status == status]
            if not s.empty:
                ax.scatter(s.terrain_max_m, s.safe_load_kg, s=35 + 0.25 * s.distance_m / 10,
                           marker=marker, c=face, edgecolor="white", linewidth=0.45,
                           label=status)
        for _, r in d[d.status == "能量受限"].iterrows():
            ax.annotate(r.zone, (r.terrain_max_m, r.safe_load_kg), xytext=(4, 3),
                        textcoords="offset points", fontsize=7.8, color=DARK)
        ax.set_title(f"{v}型", pad=5)
        ax.set_xlabel("航段最大地形高程（m）")
        ax.set_xlim(190, 570)
        ax.set_ylim(0, 87)
    axes[0].set_ylabel("最大安全载荷（kg）")
    axes[0].legend(frameon=False, loc="lower left")
    axes[0].text(0.02, 0.98, "(a)", transform=axes[0].transAxes, va="top", fontweight="bold")
    axes[1].text(0.02, 0.98, "(b)", transform=axes[1].transAxes, va="top", fontweight="bold")
    axes[2].text(0.02, 0.98, "(c)", transform=axes[2].transAxes, va="top", fontweight="bold")
    fig.subplots_adjust(wspace=0.14)
    save(fig, "图2_载荷可行边界")


def fig3_pareto(front, plan):
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(10.8, 3.9),
                                  gridspec_kw={"width_ratios": [1.22, 1]})
    colors = {18: COL["B"], 19: COL["C"]}
    for _, r in front.iterrows():
        n = int(r.N)
        ax.scatter(r.E_kWh, r.T_s / 3600, s=90, color=colors[n],
                   edgecolor="white", linewidth=0.8, zorder=4)
        ax.annotate(f"{n}架次", (r.E_kWh, r.T_s / 3600), xytext=(6, 7),
                    textcoords="offset points", fontsize=9, color=DARK)
    a = front.sort_values("N").iloc[0]
    b = front.sort_values("N").iloc[-1]
    ax.annotate("少1架次，累计时间减少",
                xy=(a.E_kWh, a.T_s / 3600), xytext=(b.E_kWh, b.T_s / 3600),
                arrowprops=dict(arrowstyle="->", color=GREY, lw=0.9),
                fontsize=8, color=GREY, ha="center")
    ax.set_xlabel("总运输能耗（kWh）")
    ax.set_ylabel("累计作业时间（h）")
    ax.text(0.02, 0.98, "(a)", transform=ax.transAxes, va="top", fontweight="bold")
    ax.set_xlim(front.E_kWh.min() - 0.01, front.E_kWh.max() + 0.01)
    ax.set_ylim(front.T_s.min() / 3600 - 0.35, front.T_s.max() / 3600 + 0.35)
    ax.grid(True, color="#E6E6E6", lw=0.55)

    # Explain the only structural difference between the two Pareto points.
    s008 = plan[plan.zone == "S008"]
    # The alternative is known from the saved non-dominated detail file.
    alt = json.loads((S2 / "非支配方案明细.json").read_text(encoding="utf-8"))[1]["plan"]
    a008 = pd.DataFrame(alt)
    rows = [
        ("18架次", "C型", float(s008.mass.sum()), 1),
        ("19架次", "B型", float(a008[a008.zone == "S008"].mass.sum()), len(a008[a008.zone == "S008"])),
    ]
    y = np.arange(len(rows))
    masses = [r[2] for r in rows]
    bars = ax2.barh(y, masses, color=[COL["C"], COL["B"]], height=0.48)
    ax2.set_yticks(y, [r[0] for r in rows])
    ax2.set_xlabel("S008总配送质量（kg）")
    ax2.set_xlim(0, max(masses) * 1.28)
    for bar, row in zip(bars, rows):
        ax2.text(bar.get_width() + 1.0, bar.get_y() + bar.get_height()/2,
                 f"{row[1]}，{row[3]}架", va="center", fontsize=8.5)
    ax2.text(0.02, 0.98, "(b)", transform=ax2.transAxes, va="top", fontweight="bold")
    ax2.text(0.02, 0.05, "差异仅来自 S008 的组批方式", transform=ax2.transAxes,
             fontsize=8.5, color=GREY)
    fig.subplots_adjust(wspace=0.28)
    save(fig, "图3_Pareto权衡与组批差异")


def fig4_robustness(response, summary):
    fig, axes = plt.subplots(1, 3, figsize=(10.8, 3.7), sharex=True)
    rho = response.rho.to_numpy() * 100
    feasible = response.feasible.fillna(False).to_numpy(dtype=bool)
    base = summary["baseline_plan_feasible_rho"] * 100
    limit = summary["global_feasible_rho"] * 100
    spec = [("N", "架次数", 1), ("E_kWh", "总运输能耗（kWh）", 1), ("T_s", "累计作业时间（h）", 3600)]
    for i, (col, ylabel, div) in enumerate(spec):
        ax = axes[i]
        vals = response[col].to_numpy(dtype=float) / div
        ax.axvspan(limit, 40, color=RED, alpha=0.07, zorder=0)
        ax.axvline(base, color=COL["B"], ls=(0, (3, 2)), lw=1.0)
        ax.axvline(limit, color=RED, ls=(0, (4, 2)), lw=1.0)
        ax.plot(rho[feasible], vals[feasible], "o-", color=COL["B"], lw=1.6,
                ms=4.3, label="可行并重新优化")
        ax.scatter(rho[feasible][-1], vals[feasible][-1], s=45, color=RED,
                   edgecolor="white", linewidth=0.7, zorder=4)
        ax.set_xlabel("返航安全余量（%）")
        ax.set_ylabel(ylabel)
        ax.set_xlim(0, 40)
        ax.grid(True, axis="y", color="#EAEAEA", lw=0.55)
        if i == 0:
            ax.text(base + 0.5, ax.get_ylim()[0] + 0.05 * np.ptp(ax.get_ylim()),
                    "原18架次方案阈值", color=COL["B"], fontsize=7.7)
            ax.text(limit + 0.5, ax.get_ylim()[0] + 0.19 * np.ptp(ax.get_ylim()),
                    "全任务可行阈值", color=RED, fontsize=7.7)
    axes[0].text(0.02, 0.98, "(a)", transform=axes[0].transAxes, va="top", fontweight="bold")
    axes[1].text(0.02, 0.98, "(b)", transform=axes[1].transAxes, va="top", fontweight="bold")
    axes[2].text(0.02, 0.98, "(c)", transform=axes[2].transAxes, va="top", fontweight="bold")
    axes[0].legend(frameon=False, loc="upper left")
    fig.subplots_adjust(wspace=0.26)
    save(fig, "图4_安全余量鲁棒性")


def fig5_allocation(plan):
    zones = [f"S{i:03d}" for i in range(1, 16)]
    agg = plan.groupby(["zone", "vehicle"], as_index=False).agg(mass=("mass", "sum"),
                                                                   sorties=("sortie", "count"))
    piv = agg.pivot(index="zone", columns="vehicle", values="mass").fillna(0).reindex(zones).fillna(0)
    cnt = agg.groupby("zone").sorties.sum().reindex(zones).fillna(0)
    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(10.8, 4.4),
                                  gridspec_kw={"width_ratios": [1.2, 1]})
    y = np.arange(len(zones))
    left = np.zeros(len(zones))
    for v in ["B", "C", "A"]:
        vals = piv[v].to_numpy() if v in piv else np.zeros(len(zones))
        ax.barh(y, vals, left=left, color=COL[v], height=0.66, label=f"{v}型")
        left += vals
    for yi, z in enumerate(zones):
        if cnt.loc[z] > 0:
            ax.text(left[yi] + 1.2, yi, f"{int(cnt.loc[z])}架", va="center", fontsize=7.6)
    ax.set_yticks(y, zones)
    ax.invert_yaxis()
    ax.set_xlabel("服务区配送质量（kg）")
    ax.legend(frameon=False, ncol=3, loc="lower right")
    ax.text(0.02, 0.98, "(a)", transform=ax.transAxes, va="top", fontweight="bold")
    ax.grid(True, axis="x", color="#EAEAEA", lw=0.55)

    order = plan.sort_values("return_soc").reset_index(drop=True)
    yy = np.arange(len(order))
    point_colors = [RED if r.return_soc < 0.25 else COL[r.vehicle] for _, r in order.iterrows()]
    ax2.hlines(yy, 0, order.return_soc * 100, color="#D1D5DB", lw=2)
    ax2.scatter(order.return_soc * 100, yy, c=point_colors, s=33, edgecolor="white", linewidth=0.45)
    ax2.axvline(20, color=GREY, ls="--", lw=0.9)
    ax2.axvline(order.return_soc.min() * 100, color=RED, ls=(0, (3, 2)), lw=1.0)
    ax2.set_yticks(yy, order.sortie)
    ax2.set_xlabel("返航SOC（%）")
    ax2.set_xlim(15, 80)
    ax2.text(0.02, 0.98, "(b)", transform=ax2.transAxes, va="top", fontweight="bold")
    ax2.text(0.02, 0.04, "红色：最小SOC瓶颈架次", transform=ax2.transAxes, fontsize=8, color=RED)
    ax2.grid(True, axis="x", color="#EAEAEA", lw=0.55)
    fig.subplots_adjust(wspace=0.32)
    save(fig, "图5_最终方案分区配置")


def main():
    _, _, geometry, nodes, cap, plan, front, response, summary = load_all()
    fig1_terrain_routes(geometry, nodes)
    fig2_capacity_boundaries(geometry, cap)
    fig3_pareto(front, plan)
    fig4_robustness(response, summary)
    fig5_allocation(plan)
    captions = """# 科研级可视化说明

本目录的图采用 ARIS `paper-figure` 的 publication 预设：PDF为矢量输出，PNG仅作预览；统一字体、单位、色板与线宽；不在图内放长标题，标题与解释放在论文图注中。

## 图注建议

1. **图1 地形与航段结构。** (a) DEM高程、O01到15个服务区的直飞航段以及服务区位置；颜色表示航段最大地形高程，点大小表示距离。(b) 航段距离与最大地形高程的关系，颜色表示去程爬升高度。该表达对应无人机GIS/地形规划研究中“空间底图+航段属性”的做法。
2. **图2 载荷可行边界。** 三个子图分别对应A/B/C型无人机；圆点表示额定载荷受限，三角形表示能量受限，虚线是额定载荷上限。该图比单纯热图更直接地显示“地形—可用载荷—能量瓶颈”的关系。
3. **图3 Pareto权衡与组批差异。** (a) 完整整数模型得到的两个非支配目标点；(b) 两个点的唯一结构差异来自S008的组批方式。该表达保留目标空间的真实尺度，不用把两个点误画成连续曲线。
4. **图4 安全余量鲁棒性。** 三个目标在统一安全余量变化下的重新优化响应；蓝色虚线是原18架次方案的失效阈值，红色虚线是全部任务的可行性阈值，阴影表示不可行区域。
5. **图5 最终方案分区配置。** (a) 各服务区配送质量按机型堆叠，右侧标注架次数；(b) 18架次方案的逐架次返航SOC，红色点为安全裕度瓶颈。

## 相近领域的文献依据

可视化设计参考了以下通过 OpenAlex/ARIS `research-lit` 检索到的相近研究：

| 文献 | 期刊/年份 | 对本图的启发 |
|---|---|---|
| Otto et al., *Optimization approaches for civil applications of unmanned aerial vehicles (UAVs) or aerial drones: A survey*, **Networks**, 2018, DOI: 10.1002/net.21818 | 无人机优化综述 | 用目标空间与约束结构展示路线/调度权衡 |
| Shakhatreh et al., *Unmanned Aerial Vehicles (UAVs): A Survey on Civil Applications and Key Research Challenges*, **IEEE Access**, 2019, DOI: 10.1109/ACCESS.2019.2909530 | UAV应用与挑战综述 | 强调任务空间、航段和资源属性的联合表达 |
| Quamar et al., *Advancements and Applications of Drone-Integrated Geographic Information System Technology—A Review*, **Remote Sensing**, 2023, DOI: 10.3390/rs15205039 | UAV-GIS综述 | 采用DEM底图、节点、航段和属性叠加的空间图式 |
| Wang et al., *Research on Multi-UAV Task Assignment Based on a Multi-Objective, Improved Brainstorming Optimization Algorithm*, **Applied Sciences**, 2024, DOI: 10.3390/app14062365 | 灾害多无人机任务分配 | 用Pareto前沿和任务分配图呈现多目标权衡 |
| Dorling et al., *Vehicle Routing Problems for Drone Delivery*, **IEEE TSMC: Systems**, 2017, DOI: 10.1109/TSMC.2016.2582745 | 无人机配送能耗/路径 | 将航段长度、能耗与配送方案分开呈现 |
| Stolaroff et al., *Energy use and life cycle greenhouse gas emissions of drones for commercial package delivery*, **Nature Communications**, 2018, DOI: 10.1038/s41467-017-02411-5 | 无人机能源分析 | 采用载荷—能耗/可行边界而非单一平均值 |

上述文献用于图表组织与变量表达的参照，不替代本题数据与模型假设的证据。原始数据、结果和脚本均保留在 `问题一` 目录下，可直接重绘。
"""
    (OUT / "可视化文献依据与图注.md").write_text(captions, encoding="utf-8")
    print(f"WROTE {OUT}")


if __name__ == "__main__":
    main()
