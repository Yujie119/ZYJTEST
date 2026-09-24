# 问题一代码与结果

科研级图表位于 `科研级可视化/`：运行

```powershell
& 'E:\tool\anaconda3\python.exe' '.\science_figures_q1.py'
```

可重绘 5 张数据图，并保留 1 张可编辑 FigureSpec 流程图。设计依据、图注和相近领域文献见 `科研级可视化/可视化文献依据与图注.md`。

先阅读 `问题一求解结果.md`。正式文件 `问题一_结果提交.xlsx` 的 `Q1_单点组批` 只包含最终18架次，其他问题未填写。

全部重算（双GPU、8个CPU工作进程）：

```powershell
& 'E:\tool\anaconda3\python.exe' '.\solve_q1.py'
```

仅计算加参数 `--compute-only`。仅从已有数值导出Excel、图表、报告并核验：运行 `report_q1.py`。单独核验：运行 `verify_q1.py`。

前提：原始文件仍在同级D题目录；使用指定Anaconda Python及已有numpy、pandas、scipy、openpyxl、matplotlib、Pillow、psutil、CUDA版PyTorch；两张CUDA设备可用。程序不安装包、不改原始附件。GPU只负责批量物理计算，LP/MILP由CPU上的HiGHS完成。

设置：E_cal=E_use；η=0.72；基准安全余量20%；目标按完整基准Pareto范围归一化；等权中心、L1半径1/3。第一问不含实体机、电池时序、通信和时限约束。

模板往返时间=去回程飞行时间，累计作业时间还含准备、装载、交接。八列表头属于原模板Q2，另存八列视图中的实体编号与绝对时刻留空。详细参数和适用范围见报告。
