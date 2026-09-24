"""Synchronize only chapter 5, preserving outside bytes and every image token.

The first run saves the exact original chapter. Reruns deterministically derive
chapter 5 from that backup and current final JSON, retaining current surrounding
chapters byte-for-byte (including edits made independently there).
"""
from __future__ import annotations
import os
for k in ['OMP_NUM_THREADS','MKL_NUM_THREADS','OPENBLAS_NUM_THREADS']:
    os.environ[k]='1'
os.environ['MKL_THREADING_LAYER']='SEQUENTIAL'
import gzip,hashlib,json,re,sys
from pathlib import Path
from collections import Counter
HERE=Path(__file__).resolve().parent;Q2=HERE.parent;ROOT=Q2.parent
sys.path.insert(0,str(Q2))
from q2_data import load_data,save_json

def read(p):return json.loads(p.read_text(encoding='utf-8'))
def digest(x):return hashlib.sha256(x).hexdigest()
def split(raw):
    start=re.search(rb'(?m)^# 5 ',raw);end=re.search(rb'(?m)^# 6 ',raw)
    if not start or not end or start.start()>=end.start():raise ValueError('chapter boundaries')
    return raw[:start.start()],raw[start.start():end.start()],raw[end.start():]
def images(raw):
    return re.findall(rb'!\[[^\]]*\]\([^\r\n]*?\)|<img\b[^>]*>',raw)
def placeholders(txt):
    return re.findall(r'^\*\*【图5-[^\n]+',txt,re.M)

def main():
    doc=ROOT/'正文/正文.md';before=doc.read_bytes();pre,current,post=split(before)
    backup=HERE/'正文_第5章_同步前备份.md'
    if not backup.exists():backup.write_bytes(current)
    original=backup.read_bytes();nl='\r\n' if b'\r\n' in original else '\n'
    s=original.decode('utf-8').replace('\r\n','\n');initial=s
    plan=read(HERE/'最终方案.json');arc=read(HERE/'联合非支配档案.json')
    summary=read(HERE/'汇总.json');raw=read(HERE/'原始数据核验.json')
    check=read(HERE/'独立核验.json');data=load_data()
    assert check['checks']['all'] and raw['all']
    with gzip.open(HERE/'frozen_evaluation_candidates.json.gz','rt',encoding='utf-8') as f:pool=json.load(f)
    types=Counter(r['vehicle'] for r in plan['routes']);visits=Counter(len(r['events']) for r in plan['routes'])
    hard=[data['boxes'][b['box']]['deadline']-b['delivery'] for b in plan['boxes'] if data['boxes'][b['box']]['hard']]
    late=lambda p:sum(b['delivery']>data['boxes'][b['box']]['expected']+1e-7 for b in p['boxes'] if not data['boxes'][b['box']]['hard'])
    min_soc=min(r['soc'] for r in plan['routes']);last=max(plan['routes'],key=lambda r:r['finish'])
    def replace(old,new):
        nonlocal s
        if s.count(old)!=1:raise ValueError(f'unique anchor: {old[:70]} count={s.count(old)}')
        s=s.replace(old,new,1)
    def section_between(a,b,new):
        nonlocal s
        i=s.index(a);j=s.index(b,i);s=s[:i]+new+s[j:]
    def table_after(title,new):
        nonlocal s
        i=s.index(title)+len(title);begin=s.index('|',i);end=s.index('\n\n',begin)
        s=s[:begin]+new.rstrip()+s[end:]

    replace('在目标层面，保留架次数和总能耗，以全部运输无人机最晚返场时刻衡量完成时间，并以普通物资加权平均迟到衡量及时性。求解以直接联合MILP为主：在同一候选库内同时开放组批、访问路线、机型、实体无人机、电池及开始时刻，依次完成单目标预求解、自适应ε搜索、连续松弛和偏好极点评价。ALNS保留为采用同一物理规则的简化对照，其产生的可行方案可作为联合模型初始解并进入共同评价档案。最后以最坏遗憾上界最小准则选出一套提交方案。这里的联合求解范围明确限定为所生成候选库，不等同于对全部可能路线的全局最优认证。',
        '在目标层面，保留架次数和总能耗，以全部运输无人机最晚返场时刻衡量完成时间，并以普通物资加权平均迟到衡量及时性。以同一联合MILP作为可行性与真实目标的计算核心，结合直接联合MILP探索、覆盖与机型工作量主问题产生新箱组、完整双资源调度及终端精修开展混合搜索。ALNS保留为采用同一物理规则的补充搜索与简化对照。将全部完整可行方案合并后，在共同冻结评价库和偏好尺度下以最坏遗憾上界最小准则选择一套提交方案；22架次是搜索与选择的结果，不是预设等式或架次上限。有限候选与有界计算不能提供全部可能路线的全局最优认证。')
    replace('本章不引入问题三的通信和中继约束，也不预先固定问题四的任务分区。偏好设置、候选生成策略和邻域算子属于本文的方法设计，不作为题目给定条件。',
        '本章不引入问题三的通信和中继约束，也不预先固定问题四的任务分区。偏好设置、候选生成策略和邻域算子属于本文的方法设计，不作为题目给定条件。专家补充允许在有电池的地点换电、禁止携带备用电池，并规定共享电池初始均位于O01。当前实施方案每架次携带一块装机电池、全程不换电、仅在O01换电充电，因此属于兼容该补充的可行子模型；本文不把“O01以外禁止换电”写成题设，也不据此证明包含站外电池迁移与换电决策的完整空间最优。')
    replace('因此，$q_{k,J_k}=v_{k,J_k}=0$。本问题只安排从调度中心带出物资，不增设服务区装货或补能能力，所以起飞质量、体积达到沿途最大值。候选架次的基本装载要求为',
        '因此，$q_{k,J_k}=v_{k,J_k}=0$。当前可行子模型仅从调度中心带出物资，不凭空增加服务区库存或供电；一个架次内不发生换电，起飞质量、体积达到沿途最大值。该限制用于界定已实现搜索范围，并非专家补充禁止站外换电。候选架次的基本装载要求为')
    ct=Counter(r['vehicle'] for r in pool);cv=Counter(len(r['events']) for r in pool)
    table_after('**表5-1 候选枚举与实际联合求解范围**',
        '| 范围 | 数量 | 解释 |\n| --- | ---: | --- |\n'
        '| 完整单点逐箱候选 | 19525 | 全部服务区非空箱号子集和三机型，经过物理与局部硬时限筛选 |\n'
        '| 旧预实验工作库 $\\mathcal K_0$ | 558 | 仅作为历史范围，旧库下界不可移用于扩大库 |\n'
        f'| 本轮冻结评价库 | {len(pool)} | 保留既有方案候选并扩展多点路线；不声称完整多点枚举 |\n'
        f'| 本轮A/B/C型候选 | {ct["A"]} / {ct["B"]} / {ct["C"]} | 三种机型全部保留 |\n'
        f'| 本轮按交付事件数统计 | {"；".join(f"{k}次：{v}" for k,v in sorted(cv.items()))} | 访问数属于搜索记录，不是题设上限 |\n'
        '| 未覆盖货箱 | 0 | 完整方案另经实际资源与硬时限核验 |')
    old='为控制成对资源约束规模，完整单点目录与实际MILP工作库分开保存。本轮每个区域—机型按两类排序各取前4条，另保留全部可行单箱及原箱组的机型替换；多点生成随机抽取2—5个区域的医疗箱路线，并补充100次普通跨区组合试探及四站回归路线。上述抽样和数量限制属于算法搜索策略，不能解释为题目禁止其他箱组、更多访问或重复访问。路线数据结构允许非相邻重复服务区；本轮没有完整枚举多点路线。候选库标识为 `0c46fcdb4bd139746e0a4e8b2583d3b6f6fdc449861233cfee690a804b21fb04`。'
    replace(old,'为控制成对资源约束规模，完整单点目录、累计发现库、直接MILP工作子集和共同评价库分别保存。558条工作库及其固定抽样规则属于旧预实验；本轮在28,216条冻结库上生成覆盖箱组，对所选路线落实完整双资源排程，并与直接联合MILP和ALNS得到的档案合并。路线结构允许非相邻重复服务区，当前库仍未完整枚举多点路线。最终评价库的物理系数指纹为 `'+summary['library_coefficient_sha256']+'`，所有极点基准和入档方案均按该范围核对。')
    replace('其中，$\\omega_b$ 继承附件应急优先系数，$L(X)$ 为其他物资的加权平均迟到量。$C_{\\max}(X)$ 严格对应题目定义的全部运输无人机最后返场的最晚时刻，不计入任务结束后的最终充电时间。',
        '其中，$\\omega_b$ 继承附件应急优先系数，$L(X)$ 为其他物资的加权平均迟到量。$C_{\\max}(X)$ 严格对应题目定义的全部运输无人机最后返场的最晚时刻，不计入任务结束后的最终充电时间。对每架实际执行任务的无人机先取其最后返场时刻，再在无人机间取最大值，与式（5-17）对全部已选架次返场时刻取最大值相同；未使用无人机不增加工期。')
    replace('在 $\\mathcal K_0$ 上一次建立式（5-10）—（5-18），所有架次选择、资源分配、开始时刻及有效排序变量均开放。分别最小化 $N,E,C_{\\max},L$ 得到四个单目标预求解记录，再在同一模型中处理各ε情景；不存在以总路线时长或紧迫度评分替代真实目标的第二套选择模型。',
        '直接联合MILP在明确记录的工作库上建立式（5-10）—（5-18），同时开放架次选择、资源分配、开始时刻及有效排序变量，并处理各单目标或ε情景。为扩大箱组搜索，本轮另在全部28,216条候选上求解逐箱恰好覆盖的0-1主问题，以架次数、能耗和机型平均工作量产生候选组合；其工作量变量仅是搜索代理。随后固定该组合，重新开放全部实体无人机、电池和开始时刻，求解真实双资源调度并核验硬时限和四目标。主问题有整数解不代表调度可行，主问题工作量也不等于真实工期。')
    replace('ALNS使用同一冻结候选库和同一独立核验器，从已修正及时性的原20架次方案出发；它是补充对照，不替代主算法的全库联合模型。本轮进行15次迭代，每次释放3个架次，采用随机、硬时限压力、充电时长和能耗四类破坏算子。充电时长是搜索启发信息，不直接等同于实际电池等待。',
        '旧预实验ALNS使用同一冻结工作库和同一独立核验器，从已修正及时性的原20架次方案出发，进行15次迭代、每次释放3个架次，采用随机、硬时限压力、充电时长和能耗四类破坏算子。以下具体参数用于描述这次历史对照；后续扩大库搜索独立保留运行配置，不把其预算混入旧对照。充电时长是搜索启发信息，不直接等同于实际电池等待。')
    replace('按照Ropke和Pisinger的ALNS思想，算子概率和权重更新为','以Ropke和Pisinger（2006）的ALNS研究为方法背景，本文采用如下算子概率与权重更新实例化。现有证据已核实该文书目信息，未取得全文核对，故不将下式标为已核实的原文公式：')
    replace('局部路线—资源联动结构参考Liu等相关研究，但题目要求满电复用，不采用其允许部分充电投入任务的条件。不同方法的实际预算分别记录，本轮不以两个预算不同的试算断言方法优劣。',
        '文献[R2]用于有限电池资源与运输决策耦合的研究背景，目前仅核实著录信息，未核验完整算法或充电规则；因此，不将本文局部MILP、ALNS组合及任何“部分充电”条件归因于该文。本文的路线—资源修复由式（5-10）—（5-18）自行构造，执行题目满电复用要求。不同方法实际预算分别记录，不以预算不同的试算断言方法优劣。')
    replace('其含义是在不同可接受偏好下，控制相对于该偏好最佳方案的最大损失。最小最大遗憾的偏好集合思想参考Benati和Conde的研究，具体四指标与偏好范围由本文建立。',
        '其含义是在不同可接受偏好下，控制相对于该偏好最佳方案的最大损失。文献[R4]仅作为稳健偏好建模的背景资料；本文未以其全文核实以下L1偏好集合、极点论证及遗憾上下界原式。式（5-26）—（5-30a）均按本题四指标自行定义并作下述推导，不将这些具体公式归为该文结论。')
    replace('本轮在直接联合求解前冻结工作库，之后不改变库，故 $\\mathcal K_f=\\mathcal K_0$。基准偏好半径为 $\\delta=0.3$，通过非负单纯形与L1球的活跃约束组合枚举全部12个合法极点。对各极点求解同一资源约束下的加权MILP及LP松弛，得到该固定候选模型的基准上下界。若只在该库获得认证，最终选择与界差也仅在该范围解释。极点求解发现的新可行方案同时加入档案，重新进行非支配过滤，并统一重算全部方案的遗憾。',
        '本轮将旧档案、新覆盖搜索及分型精修的候选统一到28,216条冻结评价库 $\\mathcal K_f$，不再采用旧库 $\\mathcal K_0$ 的下界。基准偏好半径 $\\delta=0.3$，由非负单纯形与L1球的活跃约束组合得到12个合法极点。对每个极点，在同一评价库求解逐箱覆盖与式（5-25）机型工作量连续松弛，并将迟到放宽为0，获得完整资源调度模型的有效库内下界；实际可行档案提供相同加权量的上界。省略实体资源冲突和硬时限约束只用于松弛下界，不表示提交方案可以省略这些约束。12个松弛均达到最优后，统一重算14套实际方案的遗憾区间。该界评价始终限于共同候选与O01换电子模型，不扩大为站外换电完整空间认证。')
    replace('本轮没有在ALNS中继续生成库外路线，也没有执行动态扩大释放窗口；这些属于后续扩展计划。',
        '上述旧预实验没有在ALNS中继续生成库外路线，也没有执行动态扩大释放窗口；后续扩大库分支的候选生成与释放设置另按其运行配置记录。')
    replace('每3次迭代更新一次，未使用算子保持原权重；本轮 $\\lambda=0.25$、$\\vartheta_{min}=0.05$。',
        '旧预实验每3次迭代更新一次，未使用算子保持原权重；其 $\\lambda=0.25$、$\\vartheta_{min}=0.05$。')
    replace('本轮按配置完成单目标、有限ε轮次、ALNS迭代及偏好极点任务后停止，每个MILP调用设置单独时限。',
        '旧预实验按配置完成单目标、有限ε轮次、ALNS迭代及偏好极点任务后停止；本轮扩大库采用另外记录的覆盖、排程和精修预算，每个MILP调用均设置单独时限。')
    replace('| 正式10次重复 | 尚未执行，本轮是种子202600的审计修正预实验 |',
        '| 正式10次重复 | 尚未执行；本表仅列种子202600的历史审计修正预实验 |')
    replace('A0本轮仅进行了固定库、15次迭代的简化试算；以下同预算对照与消融均属待执行正式计划。',
        '表中A0的既有历史对照仅为固定库、15次迭代简化试算；后续扩大库运行不视为同预算方法比较，以下对照与消融均属待执行正式计划。')
    replace('构造三个嵌套候选库：$\\mathcal K_0$ 为本轮冻结的单点与多点工作库，$\\mathcal K_1$ 在其上加入更多单点子集及新多点候选，$\\mathcal K_2$ 进一步加入延长预算及其他初始化发现的候选。',
        '正式候选扩展实验拟另冻结三个嵌套候选库：该实验中的 $\\mathcal K_0$ 为预先确定的单点与多点基准库，须另记模型指纹，不能与旧558条预实验库或本轮28,216条评价库混称；$\\mathcal K_1$ 在其上加入更多单点子集及新多点候选，$\\mathcal K_2$ 进一步加入延长预算及其他初始化发现的候选。')
    replace('| $\\mathcal K_0$：本轮冻结工作库 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 |',
        '| $\\mathcal K_0$：正式实验另行冻结的基准库 | 待填 | 待填 | 待填 | 待填 | 待填 | 待填 |')
    replace('**表5-2 本轮预实验的冻结配置与计算状态**','**表5-2 旧预实验（558条工作库）的历史配置与状态**')
    replace('本轮只有K0内最少架次数取得整数最优认证，值为20；能耗基准的有效下界为60.703808253 kWh、可行上界为60.704972169 kWh，限时界差约0.001917%。完成时间单目标的界为[6006.725745,7567.094097] s，尚有约20.6204%的界差。12个偏好MILP均限时，LP中4个达到最优，其余不用未认证迭代值作下界。第二轮ε因阈值重复没有新增求解任务。',
        '上述旧预实验仅在558条K0中认证最少架次20；其能耗界[60.703808253,60.704972169] kWh和工期界[6006.725745,7567.094097] s均属于旧库，不能作为本轮扩大库的下界或证明。旧12个偏好MILP均限时、仅4个LP达到最优，第二轮ε因阈值重复未新增任务。上述记录保留用于追溯，不代表本轮最终结果。\n\n'
        '**表5-2a 本轮扩大库搜索与共同评价记录**\n\n'
        '| 项目 | 本轮实际记录 |\n| --- | --- |\n'
        '| 冻结评价候选 | 28,216条；系数指纹与表5-1一致 |\n'
        '| 新箱组搜索 | 全库覆盖主问题与实际双资源调度共32任务（24+8）；4进程，每求解器1线程 |\n'
        '| 主问题与调度预算 | 首轮各12 s；第二轮主问题15 s、调度12 s；实际合计185.823 s |\n'
        '| 成功情况 | 19个完整可行任务输出，按目标合并为9个本分支非支配解；失败与限时无解单列 |\n'
        '| 固定路线终端精修 | 对继承的11套方案按机型分解后重新排程，仍按完整四目标核验 |\n'
        f'| 合并档案 | {len(arc)}套非支配方案；包含旧档案、新覆盖搜索和分型精修来源 |\n'
        '| 共同评价 | 等权中心、L1半径0.3、12个权重极点；沿用冻结正尺度 |\n'
        '| 极点下界 | 本轮同库逐箱覆盖+机型工作量连续松弛，迟到放宽为0；12个LP求得最优 |\n'
        '| 极点上界 | 来自同库经核验的实际资源调度；遗憾报告上下界 |\n'
        '| 正式比较 | 10种子同预算消融、偏好与资源敏感性尚未执行 |\n\n'
        '覆盖主问题只负责搜索组合；其代理目标和固定箱组排程的最优状态不能扩大为全库联合问题求精。最终评价使用所有来源的共同库与同一冻结尺度，不拼接旧库下界。独立评价审阅结论为PASS_WITH_SCOPE_WARNINGS：数值与遗憾区间复算通过，认证范围仍限于当前候选库及O01换电子模型。')
    table3='|方案|架次数N|能耗kWh|最晚返场s|加权迟到s|普通物资迟到箱数|遗憾下界|遗憾上界|\n|---|---|---|---|---|---|---|---|\n'
    minN=min(arc,key=lambda p:(p['objective'][0],p['objective'][2]))
    minE=min(arc,key=lambda p:p['objective'][1]);minC=min(arc,key=lambda p:p['objective'][2])
    mid=min((p for p in arc if p['objective'][0]==22 and p['objective'][3]>0),key=lambda p:p['objective'][2])
    for label,p in [('架次侧重基准',minN),('能耗侧重基准',minE),('完成时间侧重基准',minC),('较低能耗折中方案',mid),('最终代表（零迟到）',plan)]:
        f=p['objective'];table3+='|'+label+'|'+str(f[0])+'|'+f'{f[1]:.6f}|{f[2]:.6f}|{f[3]:.6f}|{late(p)}|{p["regret_lower"]:.6f}|{p["regret_upper"]:.6f}|\n'
    table_after('**表5-3 四目标基准与最终代表方案（时间单位均为s）**',table3)
    replace('各侧重基准取自本轮共同档案；遗憾界属于同一冻结K0和同一偏好尺度。原发布方案及固定资源反例仅作实现修正对比，未将其旧评价尺度混入本轮遗憾值。',
        '各侧重基准均取自本轮14套共同非支配档案，所有遗憾界对应28,216条共同评价库与同一冻结偏好尺度。这里的基准是档案中该项指标较优的可行方案，不是原问题已认证极值。零迟到方案有多套，不能仅凭 $L=0$ 选出唯一方案；最终代表依据共同最坏遗憾上界选择。')
    a='最终代表为 $N=28$、';i=s.index(a);j=s.index('\n\n',i)
    replace(s[i:j],
        '最终代表为 $N=22$、$E=65.518517$ kWh、$C_{\\max}=6206.344443$ s（103.439074 min）、$L=0$，共同遗憾区间为[0.011537,0.189051]。相对20架次零迟到基准，增加2架次与0.056005 kWh，完成时间缩短675.311405 s；相对最快的23架次方案，少1架次、节省3.035892 kWh，完成时间增加66.411326 s。相对22架次较低能耗折中方案，增加0.918287 kWh，完成时间缩短211.727751 s，并将加权迟到由21.605817 s降为0。该比较说明最终选择来自四指标权衡，而不是把架次数硬固定为22。\n\n'
        '最终组合来源于全库覆盖搜索的cover_04_0任务，再经终端联合资源精修与共同评价选择。该任务的固定路线调度返回最优，只认证其记录权重下的固定路线资源子问题；完整路线空间与站外换电空间未获最优认证。偏好半径敏感性尚未执行，图5-3(b)保持占位。')
    table4='|架次编号|无人机编号|机型编号|电池编号|开始时刻（s）|访问服务区顺序|返回O01时刻（s）|架次能耗（kWh）|\n|---|---|---|---|---|---|---|---|\n'
    for r in plan['routes']:
        seq='→'.join(['O01']+[e['zone'] for e in r['events']]+['O01'])
        table4+=f'|{r["route_id"]}|{r["uav"]}|{r["vehicle"]}|{r["battery_id"]}|{r["start"]:.6f}|{seq}|{r["finish"]:.6f}|{r["energy"]:.6f}|\n'
    table_after('**表5-4 最终逐架次运输与资源分配明细**',table4)
    replace('本方案实际执行28架次，A/B/C型分别执行13/8/7架次，28架次均访问一个服务区。80箱覆盖与目的地检查通过；31箱硬时限全部满足，最小裕度为78.397485 s；普通物资迟到5箱。最晚返场对应无人机U07的架次Q2-0028。候选含多点路线并不意味着代表方案必须使用多点路线，本轮结果不单独证明多点访问的效益。',
        f'本方案执行22架次，A/B/C型分别为{types["A"]}/{types["B"]}/{types["C"]}架次，其中17架次访问一个服务区、5架次访问两个服务区。实际使用7架无人机，U01未使用；14块共享电池均至少使用一次。80箱覆盖与目的地检查通过，31箱硬时限全部满足，最小裕度{min(hard):.6f} s；其余49箱均无迟到。最晚返场为无人机{last["uav"]}的架次{last["route_id"]}。该实例使用多点路线，但其独立收益仍需同预算单点对照，不能由一套代表方案直接作因果判断。\n\n'
        f'全部货箱最后交付发生于{max(b["delivery"] for b in plan["boxes"]):.6f} s，全部运输最晚返场发生于{max(r["finish"] for r in plan["routes"]):.6f} s，最后一次充满发生于{max(r["recharge"] for r in plan["routes"]):.6f} s。三者含义不同，本题完成时间采用其中的最晚返场时刻。')
    table_after('**表5-5 逐箱与资源可行性核验汇总**',
        '|核验项目|实际结果|\n|---|---|\n|80箱精确覆盖及目的地|全部通过|\n'
        f'|31箱硬时限|全部满足；最小裕度{min(hard):.6f} s|\n'
        '|49箱普通物资期望时限|全部满足；迟到箱数0、加权迟到0 s|\n'
        '|质量、体积与逐段载荷|全部通过|\n'
        f'|返航SOC|最小{100*min_soc:.6f}%，满足20%余量|\n'
        '|实体无人机占用|库存8架，实际使用7架，U01未使用；机型匹配且无重叠|\n'
        '|电池占用与满电复用|库存14块均有使用；型号匹配、任务及充电无冲突|\n'
        '|电池位置与备用电池|初始均O01，所有换电均O01，每架次仅携带装机电池|\n'
        f'|原始数据复算|{raw["checks_count"]}项通过；另由生产独立核验重算四目标|\n'
        '|共同评价复核|14套方案、135条去重路线通过；遗憾公式与数据复算通过，保留范围警示|')
    replace('全部8架无人机及14块电池的使用次数、无人机占用率和充电事件已输出，未使用设备保留0次。核验器从原始箱号及机型参数重建载荷、各航段时间与能耗、SOC和充电结束；航段DEM穿越另由像元矩形相交算法交叉检查。资源等待表保存给定顺序下两类资源的就绪时刻，不能据此把全部设备空闲解释为电池瓶颈。',
        '资源表保留全部8架无人机与14块电池的清单，U01明确记为0次，避免将库存数误写为实际使用数。核验器从原始箱号及机型参数重建载荷、各航段时间与能耗、SOC和充电结束；航段DEM穿越另由像元矩形相交算法交叉检查。资源等待表保存给定顺序下两类资源就绪时刻，不能把全部空闲解释为电池瓶颈。此处通过意味着方案在已声明物理假设及O01换电子模型下可执行，不意味着模型假设或完整问题已获无条件最优证明。')
    replace('预实验采用与正式实验不同的随机种子202600，用于检查可行初始化、估计计算开销和确定基准总时间预算 $T_0$。归一化参考值、ε阈值范围、偏好中心与半径、算子参数、局部MILP时限、求解精度及各阶段时间分配在正式运行前冻结。$T_0$ 的具体秒数及配置文件标识待预实验后填入表5-2；预实验结果不混入正式重复统计。',
        '旧预实验使用种子202600，本轮扩大库各任务另有独立种子与预算日志，均不替代正式10种子同预算对照。归一化参考值、ε阈值范围、偏好中心与半径、算子参数、局部MILP时限、求解精度及各阶段时间分配须在正式运行前冻结。正式 $T_0$ 及配置标识仍待确定，不能将本轮32个有界任务作为32次独立方法重复，也不将其185.823 s总墙钟直接当作单次正式预算。')
    section_between('## 5.4 本章小结','与问题三衔接时，',
        '## 5.4 本章小结\n\n'
        '本章在统一DEM与已声明能耗假设下，建立逐箱候选覆盖、医疗与首批硬时限、普通物资迟到以及无人机—电池双资源时序的联合MILP。采用直接联合MILP探索、覆盖主问题产生箱组、完整资源调度和终端精修相结合的有界搜索，ALNS保留为补充与后续同预算对照。以28,216条共同评价库和固定偏好尺度合并14套非支配方案后，按最坏遗憾上界最小准则选出22架次方案：总能耗65.518517 kWh，全部返回O01时刻6206.344443 s，加权迟到0 s，遗憾区间[0.011537,0.189051]。提交表仅输出该套方案。\n\n'
        '方案包含5个双服务区架次，实际使用7架无人机与14块电池；80箱精确覆盖、31箱硬时限及双资源核验均通过，原始数据复算373项通过。独立评价复核确认共同遗憾计算，同时保留候选范围与模型范围警示。专家允许在有电池地点换电，而本轮方案仅在O01换电、无备用电池携带，因此是兼容补充的可执行子模型方案；未证明站外电池迁移、换电及全部多点路线空间的全局最优。\n\n'
        '32个覆盖与调度任务、11套分型精修及共同评价属于本轮改进搜索，不是正式算法性能比较。10种子同预算对照、候选与预算扩展、偏好及资源敏感性仍按第5.3.4节执行；图示占位和未运行表格不填推测数据。\n\n')
    s=s.rstrip()+'\n\n本章ALNS方法背景补充书目：ROPKE S, PISINGER D. An Adaptive Large Neighborhood Search Heuristic for the Pickup and Delivery Problem with Time Windows[J]. Transportation Science, 2006, 40(4): 455–472。当前仅核实书目信息，未以全文确认式（5-22）—（5-23），两式为本文采用的具体实例化。\n\n'
    out=s.replace('\n',nl).encode('utf-8')
    assert images(out)==images(original),'chapter image token mismatch'
    assert placeholders(s)==placeholders(initial),'figure placeholder mismatch'
    after=pre+out+post
    assert split(after)[0]==pre and split(after)[2]==post
    assert images(before)==images(after),'whole document image token mismatch'
    # Avoid silently overriding a concurrent edit anywhere in the document.
    if doc.read_bytes()!=before:raise RuntimeError('Concurrent manuscript edit; rerun against current file')
    doc.write_bytes(after)
    stats={'chapter':'5 only','source_final_sha256':digest((HERE/'最终方案.json').read_bytes()),
           'document_before_sha256':digest(before),'document_after_sha256':digest(after),
           'chapter_backup_sha256':digest(original),'chapter_after_sha256':digest(out),
           'outside_prefix_equal':split(after)[0]==pre,'outside_suffix_equal':split(after)[2]==post,
           'outside_bytes_equal':split(after)[0]+split(after)[2]==pre+post,
           'whole_image_references_equal':images(before)==images(after),
           'chapter_image_count':len(images(out)),'whole_image_count':len(images(after)),
           'figure_placeholders_equal':placeholders(s)==placeholders(initial),
           'figure_placeholder_count':len(placeholders(s)),
           'chapter_lines_before':len(initial.splitlines()),'chapter_lines_after':len(s.splitlines()),
           'routes':len(plan['routes']),'types':types,'visit_counts':visits,'actual_uavs':len({r['uav'] for r in plan['routes']}),
           'actual_batteries':len({r['battery_id'] for r in plan['routes']}),'hard_boxes':len(hard),
           'hard_min_slack':min(hard),'soft_late_boxes':late(plan),'min_soc':min_soc,
           'last_delivery':max(b['delivery'] for b in plan['boxes']),
           'last_return':max(r['finish'] for r in plan['routes']),
           'last_full_charge':max(r['recharge'] for r in plan['routes']),
           'archived_plans':len(arc),'library_columns':len(pool),'objective':plan['objective'],
           'regret_interval':[plan['regret_lower'],plan['regret_upper']]}
    save_json(HERE/'正文第5章同步核验.json',stats)
    print(json.dumps(stats,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
