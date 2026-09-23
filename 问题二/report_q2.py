# -*- coding: utf-8 -*-
"""从问题二最终方案导出逐箱时限和资源汇总，便于论文表格复核。"""
from pathlib import Path
import json
import pandas as pd

ROOT=Path(__file__).resolve().parent
SUB=ROOT/"子问题二"
plan=json.loads((SUB/"最终方案.json").read_text(encoding="utf-8"))
boxes=pd.DataFrame(plan["boxes"])
routes=pd.DataFrame(plan["routes"])

hard=boxes[boxes["hard"].astype(bool)].copy()
hard["时限裕度s"]=hard["deadline"].astype(float)-hard["delivery"].astype(float)
soft=boxes[~boxes["hard"].astype(bool)].copy()
soft["迟到量s"]=(soft["delivery"].astype(float)-soft["expected"].astype(float)).clip(lower=0)
cols=["box","zone","kind","delivery","deadline","hard","first","priority"]
hard[cols+["时限裕度s"]].rename(columns={"box":"货箱编号","zone":"服务区编号","kind":"物资类型",
    "delivery":"交付完成时刻s","deadline":"适用截止时刻s","hard":"硬时限","first":"首批保障"}).to_csv(SUB/"硬时限核验.csv",index=False,encoding="utf-8-sig")
soft[cols+["迟到量s"]].rename(columns={"box":"货箱编号","zone":"服务区编号","kind":"物资类型",
    "delivery":"交付完成时刻s","deadline":"期望时刻s","hard":"硬时限","first":"首批保障"}).to_csv(SUB/"普通物资及时性.csv",index=False,encoding="utf-8-sig")

u=[]
for key,g in routes.groupby("uav",sort=True):
    u.append({"资源类型":"实体运输无人机","资源编号":key,"机型编号":g.vehicle.iloc[0],
        "执行架次":len(g),"占用总时长s":float((g.finish-g.start).sum()),
        "最后返场s":float(g.finish.max()),"占用率":float((g.finish-g.start).sum()/routes.finish.max())})
b=[]
for key,g in routes.groupby("battery_id",sort=True):
    b.append({"资源类型":"共享电池","资源编号":key,"机型编号":g.vehicle.iloc[0],
        "使用次数":len(g),"任务总时长s":float((g.finish-g.start).sum()),
        "充电总时长s":float((g.recharge-g.finish).sum()),"最后充满s":float(g.recharge.max())})
pd.DataFrame(u+b).to_csv(SUB/"资源使用汇总.csv",index=False,encoding="utf-8-sig")
md=ROOT/"问题二求解结果.md"
old=md.read_text(encoding="utf-8") if md.exists() else "# 问题二求解结果\n"
extra=["","## 时限与资源汇总","",f"- 硬时限货箱：{len(hard)}箱，最小时限裕度：{hard['时限裕度s'].min():.3f} s。",f"- 普通物资迟到：{int((soft['迟到量s']>0).sum())}箱，加权迟到量：{(soft.priority*soft['迟到量s']).sum()/soft.priority.sum():.3f} s。", "", "### 资源使用", "", "|资源类型|资源编号|机型|执行/使用次数|占用或任务总时长(s)|充电总时长(s)|占用率|", "|---|---|---|---:|---:|---:|---:|"]
for x in u+b:
    extra.append("|"+"|".join(str(x.get(k,"")) for k in ["资源类型","资源编号","机型编号","执行架次" if x["资源类型"]=="实体运输无人机" else "使用次数","占用总时长s" if x["资源类型"]=="实体运输无人机" else "任务总时长s","充电总时长s","占用率"])+"|")
md.write_text(old+"\n".join(extra)+"\n",encoding="utf-8")
print({"hard_boxes":len(hard),"min_hard_margin_s":float(hard["时限裕度s"].min()),
       "soft_late_boxes":int((soft["迟到量s"]>0).sum()),"weighted_soft_lateness_s":float(
           (soft.priority*soft["迟到量s"]).sum()/soft.priority.sum())})
