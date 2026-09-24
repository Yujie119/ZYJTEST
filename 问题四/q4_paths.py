"""Single routing table for Q4's two subproblems and shared artifacts."""
from pathlib import Path
ROOT=Path(__file__).resolve().parent
SUB1=ROOT/'子问题一'
SUB2=ROOT/'子问题二'
FILES1={
    '完整分区档案.json','分区枚举明细.csv','非支配档案.csv','MILP与LP核验.json',
    'epsilon搜索记录.csv','最终代表方案.json','Q4_分区配置.csv',
    '备选快照比较.json','共同均衡上限比较.csv','偏好与类别权重敏感性.json','计算资源记录.json',
    '问题四_结果提交.xlsx','提交表预览.png',
}
FILES2={
    '组内资源分配见证.csv','资源峰值证书.json','分组任务明细.csv','分组汇总.csv','逐箱继承核验.csv',
    '库存缺口分析.csv','固定资源事件.csv','核验报告.json','逐项核验记录.json','资源缺口原因.md',
    '合并复用收益.csv','独立配置分析.json',
}
def output(name):
    if name in FILES1:return SUB1/name
    if name in FILES2:return SUB2/name
    raise KeyError('Unregistered output: '+name)
def ensure_dirs():
    SUB1.mkdir(exist_ok=True);SUB2.mkdir(exist_ok=True)
