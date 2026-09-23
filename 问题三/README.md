# 问题三：运输—中继联合调度

所有新增代码和结果位于本目录。`缓存/问题二初始化快照.json`是求解启动时复制的初始化方案；Python代码不导入问题一、问题二的求解模块，不回写其结果。原始附件从项目根目录的`D题/数据`只读加载。

## 先看结果

- `问题三求解结果.md`：两子问题结果、完整运输/中继表和四幅科研图。
- `问题三_结果提交.xlsx`：原Q3中继/通信表，以及沿用Q2字段的Q3运输/逐箱补充表。其他问题页保持原空表。
- `子问题二/最终方案.json`：正式编号的一套方案，供问题四继承。不要把非支配档案整份作为提交方案。
- `求解摘要.json`、`子问题二/独立核验结果.json`：同一方案的四目标和核验结果。

开始时刻为开始准备时刻。Excel保存完整数值，仅显示舍入。通信表记录区间内部状态；精确事件端点的唯一保障主体见`通信事件端点核验.csv`。归一化参考固定后出现负值是允许的。

## 环境及最短核验命令

使用现有 Anaconda base，不安装或更新任何包。PowerShell 7：`C:\Program Files\PowerShell\7\pwsh.exe`；Python：`E:\tool\anaconda3\python.exe`。在项目根目录`D:\研究生\比赛\数学建模\2026`执行以下命令：

```powershell
& 'E:\tool\anaconda3\python.exe' -X utf8 '问题三\preflight_q3.py'
& 'E:\tool\anaconda3\python.exe' -X utf8 '问题三\verify_q3.py'
& 'E:\tool\anaconda3\python.exe' -X utf8 '问题三\check_q3_delivery.py'
```

预期分别打印`Q3_ENVIRONMENT_WITNESS`、核验`PASS`、`Q3_DELIVERY_PASS`。最后一条重新检查Excel数值与方案、直连优先事件表及已核验档案，并包含可手算的地形事件算例。

重建结果表和图（保留求解方案，不重跑优化）：

```powershell
& 'E:\tool\anaconda3\python.exe' -X utf8 '问题三\report_q3.py'
```

该命令再次独立核验后导出，不会将未通过核验的方案标为正式结果。

## 完整求解流水线

```powershell
& 'E:\tool\anaconda3\python.exe' -X utf8 '问题三\prepare_q3.py'
& 'E:\tool\anaconda3\python.exe' -X utf8 '问题三\solve_q3.py'
& 'E:\tool\anaconda3\python.exe' -X utf8 '问题三\supplement_q3.py'
& 'E:\tool\anaconda3\python.exe' -X utf8 '问题三\evaluate_q3.py'
& 'E:\tool\anaconda3\python.exe' -X utf8 '问题三\report_q3.py'
& 'E:\tool\anaconda3\python.exe' -X utf8 '问题三\check_q3_delivery.py'
```

完整运行会重写本目录内计算结果。HiGHS采用限时搜索，线程调度和机体/组件对称性可能使再次运行的可行方案不同；已交付结果及输入指纹可直接核验。`supplement_q3.py`若已有`缓存/补充实验初始方案.json`，复用该基线，以免把上一次补充结果递归当作新初值。

`solve_q3.py`参数默认`--iterations 8 --workers 4 --repair-seconds 12 --anchor-seconds 40`。有4个初始侧重模型、两轮各4条搜索链和档案精修；额外运行适配机型改派、冻结Q2对照、组件数量/高度上限及偏好半径对照。8条链共享档案，不能称为8次独立完整重复试验。未执行的机制图、完整消融、嵌套精度和独立重复计划仍保留占位。

## 模型与实现范围

公共物理计算为附录规则加正文假设：势能等效爬升、下降不另计能耗，中继高端点巡航面补全，30秒建链按1.10 kW计能；机体周转与能源充电并行。运输无途中主动等待，中继每架次定点悬停。

候选中继在400 m初始网格与100/200/300 m高度层筛选；双GPU处理1616个回传及能源可行候选与255个空间点的257点射线采样。保留16个水平位置，追加高度候选后共24个三维候选。GPU采样只用于筛选，完整通信由CPU扫掠三角形与闭DEM像元认证。

水平初始区间200 m、垂直100 m，必要时最多细分4层。每实体中继3个有序槽，最多6架次；搜索时域30000 s。运输候选包含1—3个不同服务区及显式副本。最终选择单点架次不代表事先限制为单点。

最终决策取已认证档案中的最小遗憾上界。下界仅对累计路线库及同一数值范围有效，使用空通信采样集并进一步移除资源顺序、中继和整数条件，保留覆盖/工作量/适用的ε上限；因此界较弱。没有全空间、全路线全局最优证明。

## 代码职责

| 文件 | 职责 |
| --- | --- |
| q3_inputs.py | 原始附件、局部米制坐标、航段与运输能源 |
| q3_common.py | 内存缓存、双GPU筛选、全区间几何证书 |
| q3_milp.py | 运输与中继资源、时刻、服务和能量联合MILP |
| solve_q3.py | 自适应ε、ALNS搜索、有效外松弛及遗憾选择 |
| supplement_q3.py | 有针对性的机型改派和冻结Q2方案对照 |
| evaluate_q3.py | 组件/高度/偏好敏感性和档案重评 |
| verify_q3.py | 从原始数据重新计算的独立核验 |
| q3_communication.py | 地形事件、距离事件和直连优先状态导出 |
| report_q3.py | Excel、CSV、JSON、Markdown和SVG/PNG图表 |
| check_q3_delivery.py | 导出关联、数值及通信事件交叉检查 |

主求解结果、额外对照结果和日志均保留。计算资源真实分工、GPU操作计数和软件版本见`计算资源记录.json`。DEM与航段、区间证书驻留内存复用；不以占满内存或显存作为效率指标。
