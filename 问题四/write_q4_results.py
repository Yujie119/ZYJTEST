"""Populate only Chapter 7 from verified Q4 artifacts; retain figure placeholders."""
from pathlib import Path
import csv,json,hashlib,shutil

HERE=Path(__file__).resolve().parent
PAPER=HERE.parent/'正文/正文.md'
from q4_paths import output
def load(name):return json.loads(output(name).read_text(encoding='utf-8'))
def table(headers,rows):
    return '\n'.join(['| '+' | '.join(headers)+' |','| '+' | '.join(['---']*len(headers))+' |']+
                     ['| '+' | '.join(str(v) for v in row)+' |' for row in rows])
def code(s):return ' / '.join('+'.join('C'+str(int(v)+1) for v in group.split('+')) for group in s.split('|'))
def vec(d):return '('+','.join(str(d[k]) for k in R)+')'
def fmt(v):return f'{v:.6f}'

audit=load('核验报告.json');assert audit['status']=='PASS'
res=load('最终代表方案.json');allrows=load('完整分区档案.json');logs=load('MILP与LP核验.json')
alt=load('备选快照比较.json');perf=load('计算资源记录.json');R=res['resource_order'];sol=res['solutions']
structure=json.loads((HERE/'输入快照/结构与字段映射.json').read_text(encoding='utf-8'))
original=PAPER.read_text(encoding='utf-8');prefix,chapter=original.split('# 7 问题四',1)
chapter='# 7 问题四'+chapter
backup=HERE/'审查与备份/正文_结果回填前.md'
if not backup.exists():shutil.copy2(PAPER,backup)
def replace(old,new):
    global chapter
    assert old in chapter,old[:100]
    chapter=chapter.replace(old,new,1)
def block(start,end,new):
    global chapter
    a=chapter.index(start);b=chapter.index(end,a)
    chapter=chapter[:a]+new.strip()+'\n\n'+chapter[b:]

replace('目标值为\n$(24,65.112050282,9165.154435,465.258364)$；',
        '目标值为\n\n$$\n(N,E,C_{\\max}^{joint},L)=(24,65.112050282\\ \\mathrm{kWh},9165.154435\\ \\mathrm{s},465.258364\\ \\mathrm{s}).\n$$\n\n')
replace('MILP提供主要求解接口，枚举是结构性核验和补充认证工具。',
        '本实例以完整枚举和十进制有理数评价为主，MILP用于交叉核验；基本单元较多时可采用完整候选组MILP接口。')
replace('求解器导致的近似同一事件应在第6章冻结前按可追溯的等式关系统一，不能在不同分组下分别调整时刻。',
        '主快照直接采用原JSON十进制表示，不对相近时刻舍入或加抖动。备选快照若有求解器浮点误差导致的严格交接重叠，则记录原值并暂停其正式配置比较；须在源方案层统一事件等式、重新核验并生成新快照后才能使用，不能在不同分组下分别调整时刻。')

component_rows=[]
for c in structure['components']:
    i=c['code'];tasks=[r for r in res['solutions']['2']['groups']]
    component_rows.append([c['label'],'、'.join(c['zones']),fmt(c['transport_work_s']),fmt(c['relay_work_s'])])
component_table='**表7-0：主快照的不可拆分基本单元。**\n\n'+table(['单元','服务区','运输工作量（s）','中继工作量（s）'],component_rows)
component_table+='\n\nC1、C3、C4分别包含4、1、1个运输架次；C2包含14个运输架次和全部4个中继架次。程序内部使用0—3编码，论文依次记为C1—C4。实际通信导出174个区间和738个事件端点；运输关联单独得到15个单元，加入实际中继任务关联后合并为4个。`slot=0,3,4,5`分别映射到本快照中的`Q3-R001、Q3-R004、Q3-R005、Q3-R006`，未按历史显示编号替换。\n\n'
replace('**【图7-1占位：运输—中继任务关联与分区基本单元】**',component_table+'**【图7-1占位：运输—中继任务关联与分区基本单元】**')

replace('因此本实例的均衡差异完全来自运输工作量，不能据此删去 $B_R$，而应将其作为结构恒定项单独报告。',r'''因此本实例的均衡差异完全来自运输工作量，中继均衡没有优化空间。正式模型仍为式（7-16）的两个目标；将中继项代入偏好函数，有

$$
\Phi_G(\Pi;\theta)=\theta A(\Pi)+\frac{1-\theta}{2}B_T(\Pi;G)+\frac{1-\theta}{2}.
\tag{7-26c}
$$

常数项在遗憾差中抵消，但运输不均衡前的1/2不能删除；直接改为运输不均衡等权求和会改变原偏好尺度。程序始终使用原定义的 $A,B$。

C2的运输工作量占比为

$$
p=\frac{26852.189303205716}{34930.5299208465}=0.7687312320784564.
$$

设包含C2的组份额为 $p_*\ge p$。对两种组数，其余组份额之和不超过 $1-p<1/G$，故各自均低于均匀份额。由式（7-14）直接得到

$$
\begin{aligned}
B_T&=\frac{G}{2(G-1)}\left[p_*-\frac1G+\sum_{h\ne h_*}\left(\frac1G-p_h\right)\right]\\
&=\frac{Gp_*-1}{G-1}\ge\frac{Gp-1}{G-1}.
\end{aligned}
\tag{7-26d}
$$

C2独立成组且其余三个单元组成其余非空组时取等号。因此两组和三组的运输不均衡最低值分别为0.537462464、0.653096848，综合不均衡最低值分别为0.768731232、0.826548424。该结论针对允许补配资源的分区域；增加组数不会拆开C2，反而降低均匀份额基准，因此不能保证改善均衡。''')

rows=[]
for lg in logs:
    g=str(lg['G']);s=sol[g];ep=lg['endpoints']
    rows.append([g,res['M'],lg['candidate_groups'],len(allrows[g]),len(lg['epsilon']),len(lg['epsilon'])-1,
                 fmt(ep[0]['value']),fmt(ep[-1]['value']),fmt(s['regret_max']),'通过'])
text='**表7-1：分区求解与稳健选择记录。**\n\n'+table(
    ['组数','基本单元数','候选组数','完整分区数','ε核验次数','非支配向量数','$v_G(0.35)$','$v_G(0.65)$','最小最大遗憾','核验'],rows)
text+='\n\nε核验次数包含最后一次不可行认证。两组阈值依次为107、91、88、79，三组为107、97、88。前两列候选组是单元子集，完整分区是覆盖全部单元的非空组集合，两者不混淆。枚举以原始十进制有理数完成比较；MILP采用浮点计算，并将所得整数方案回代有理数目标，结果一致。两端点偏好基准及直接最小最大遗憾MILP均与枚举相同。\n\n'
text+='**表7-1a：各ε子问题的有效LP下界与整数最优值。**\n\n'+table(
    ['组数','ε','$Q^*$','$B^*$','LP下界','绝对界差'],
    [[lg['G'],r['epsilon'],r['Q'] if r['Q'] is not None else '不可行',fmt(r['B']) if r['B'] is not None else '—',
      fmt(r['LP_bound']) if r['LP_bound'] is not None else '—',fmt(r['gap']) if r['gap'] is not None else '—'] for lg in logs for r in lg['epsilon']])
text+=r'''

LP下界按完整候选组模型计算，并将浮点对偶乘子转为有理数再作残差修正。设覆盖及组数等式为 $Hy=d$，资源上界为 $q^Ty\le\varepsilon$。对任意等式乘子 $u$及 $t\le0$，下式是严格有效的下界：

$$
LB=u^Td+t\varepsilon+\sum_S\min\{0,b_S-(H^Tu)_S-tq_S\}.
\tag{7-21a}
$$

这是将拉格朗日表达在 $0\le y_S\le1$ 上逐项最小化所得，避免将有浮点残差的对偶目标直接当作严格界。所有分数及乘子保存在核验文件中。表中六位小数的零界差可能包含小于 $2\times10^{-17}$ 的残差；完整枚举仍给出该固定问题的精确整数最优认证。
'''
text+=f'\n本机Python求解与导出耗时约{perf["solver_wall_seconds"]:.2f} s，包含4进程备选评价、MILP/LP和GPU初始化，未计前置快照复制、通信几何重建及后续独立核验。全部组和分区缓存在内存；主进程峰值工作集约{perf["peak_working_set_bytes"]/1024**2:.1f} MiB。两张RTX 3080 Ti分别完成112、80项候选组资源峰值张量核对，每卡峰值分配约8.1 MiB，均与精确CPU结果相同。当前规模很小，不据此宣称GPU加速收益。'
block('**【表7-1占位：','### 7.2.3',text)

front_rows=[]
for g,records in allrows.items():
    nd=[r for r in records if not any(t['A']<=r['A'] and t['B']<=r['B'] and (t['A']<r['A'] or t['B']<r['B']) for t in records)]
    for r in sorted(nd,key=lambda x:x['A']):
        role='均衡侧重／稳健代表' if r['partition_code']==sol[g]['partition_code'] else '资源侧重' if r['A']==min(x['A'] for x in records) else '中间折中'
        front_rows.append([g,role,code(r['partition_code']),fmt(r['A']),fmt(r['BT']),fmt(r['BR']),fmt(r['B']),vec(r['gaps']),fmt(r['regret_max'])])
text='**表7-2：两组与三组的完整非支配前沿及代表方案。**\n\n'+table(
    ['组数','方案侧重','基本单元分组','$A$','$B_T$','$B_R$','$B$','库存缺口向量','最大遗憾'],front_rows)
text+='\n\n表中缺口向量按式（7-6）的八类资源顺序。两组资源最优存在不同配置的同值解，表中保留其中均衡更优的非支配解。两种组数的稳健代表恰与均衡侧重代表重合，这是基准偏好下的计算结果，未预先固定均衡优先。正式提交表只填写这两个代表的5行组级配置，完整13个分区另存明细。\n\n'
text+='**表7-2a：正式代表的逐组配置。**\n\n'+table(['组数','任务组','基本单元','服务区','八类最低配置','运输工作量（s）','中继工作量（s）'],
    [[g,f'G{g}-{h:02}', '+'.join('C'+str(i+1) for i in gr['units']),'、'.join(gr['services']),vec(gr['resources']),
      fmt(gr['transport_work_s']),fmt(gr['relay_work_s'])] for g,s in sol.items() for h,gr in enumerate(s['groups'],1)])
text+='\n\n逐任务编号、80箱组归属及送达时刻、货箱数、质量和组内实体匹配另见结果明细；各组按最小服务区编号排列。运输机和能源单独配置，新编号包含所属组，执行全过程不跨组调配。'
block('**【表7-2占位：','**【图7-3占位：',text)
replace('它描述该离散方案对中的资源增加与均衡改善，不是连续导数，也不推断因果弹性。进一步指出哪些单元交换导致哪类资源峰值变化。',
r'''它描述该离散方案对中的资源增加与均衡改善，不是连续导数，也不推断因果弹性。两组从资源侧重到中间折中时，增加1架B型运输机及1组B型电池，$A$增加0.093750、$B$降低0.141860，交换率约1.513170；继续到稳健代表时，将C3从C2所在组移到C1、C4所在组，增加1组C型电池，$A$增加0.031250、$B$降低0.044705，交换率约1.430545。三组从资源侧重到稳健代表，增加1架C型运输机和1组C型电池，$A$增加0.093750、$B$降低0.114406，交换率约1.220334。这些是同组数前沿内的权衡；两种最终代表彼此比较时，仅增加1架C型机，电池需求相同。

基准偏好下，两组稳健代表相对中间折中的最坏遗憾优势仅约0.002168，因此另做偏好敏感性检查。取 $\delta=0,0.1,0.3,0.5,1$ 时，前3个设置选择表中两组均衡代表，后2个选择中间折中；三组在这5个设置下均选择同一稳健代表。将运输机、运输电池、中继资源三类中的一类权重整体乘1.5后归一化，前两种扰动使两组代表切换到中间折中，增加中继资源关注度不改变两组代表；三组在三种扰动下均不变。扰动实验直接重算有理数加权 $A$，未将原 $Q/96$误用为新权重目标。''')

text='**表7-3：八类资源的配置、集中基准与库存缺口。**\n\n'+table(
    ['类型','库存 $I_r$','集中需求 $P_r$','2组需求','2组缺口／剩余','3组需求','3组缺口／剩余'],
    [[r,res['inventory'][r],sol['2']['concentrated_P'][r],sol['2']['D'][r],f"{sol['2']['gaps'][r]}／{sol['2']['stock'][r]}",
      sol['3']['D'][r],f"{sol['3']['gaps'][r]}／{sol['3']['stock'][r]}"] for r in R])
text+='\n\n两组7个、三组6个划分中，同时满足八类库存的方案均为0；增加全部库存上限后的MILP也均证明不可行。因此本节正式方案均为“结构合法、补配后可独立执行”。即使两组代表的 $A<1$，仍有B/C型机和B/C型电池缺口，不能由A型库存余量抵消。每个组、资源类型均已保存峰值区间及同时占用任务清单。\n\n'
text+='**表7-4：分区与配置独立核验。**\n\n'+table(['核验对象','结果与证据'],[
 ['快照一致性','输入哈希、原源文件和隔离依赖核对通过；问题三源文件未改'],
 ['结构归属','15区唯一归属，分别2/3个非空组；20运输及4中继任务均完整且仅执行一次'],
 ['实际通信','174区间及738端点；实际保障运输与中继任务同组；继承原DEM全区间证书'],
 ['逐箱交付','80箱唯一继承，31箱硬时限满足，原四目标复算一致'],
 ['资源分配','两个方案共96行资源占用分配；组间编号独立，组内无冲突，数量等于峰值下界'],
 ['能源与位置','按原容量和附录充电分段复算；固定O01起讫，满电能源释放后复用'],
 ['求解交叉检查','有标签穷举独立重建13种分区，与主算法有理数目标和遗憾完全一致；MILP、LP证书及双GPU核对通过'],
 ['库存状态','两组0/7、三组0/6满足全部库存；缺口不误写为计算失败'],
 ['总核验记录',f"{audit['checks']}项通过，失败0项；详细断言和证据文件已保存"]])
text+='\n\n独立核验程序不导入主求解器的关联合并、分区枚举、峰值或目标函数：采用图遍历、有标签分配去重和事件扫描重新计算。空间通信仍继承问题三已核验DEM内核，并以同快照重建保障表，因此不称为另一套独立传播物理模型验证。'
block('**【表7-3占位：','### 7.3.2',text)

replace('本节从第6章已有且完成同级核验的方案档案中选取架次侧重、总能耗侧重、联合完成时间侧重、及时性侧重及主分析代表。',
        '本节先审计第6章精修档案的全部7个不同来源快照，再对满足同级原始数据、DEM和严格资源事件检查的主方案及3个备选独立重复同一分区流程。')
good=[a for a in alt if a['status']=='EXACT']
text='**表7-5：严格事件检查通过的运行快照及结构。**\n\n'+table(
    ['快照','总架次','总能耗（kWh）','联合完成（s）','加权迟到（s）','$M_T/M$','运输总工作量（s）','中继总工作量（s）'],
    [[a['snapshot'],int(a['objective'][0]),fmt(a['objective'][1]),fmt(a['objective'][2]),fmt(a['objective'][3]),
      f"{a['M_T']}/{a['M']}",fmt(sum(a['workT'])),fmt(sum(a['workR']))] for a in good])
text+='\n\n4个快照的最大单元均为同一12服务区集合，且包含100%的中继工作量，两种组数均结构可分。主方案与archive_06的大单元运输份额为0.768731232；archive_03与archive_05为0.770978154。这里比较的是既有运行档案的固定任务与时序，未获得不同服务区关联结构，不能据此声称验证了空间结构变化。\n\n'
text+='**表7-5a：共同均衡上限下的最低配置负担。**\n\n'+table(
    ['快照','组数','$A^*(0.80)$','$A^*(0.85)$','$A^*(0.90)$','$A^*(1.00)$'],
    [[a['snapshot'],g]+[fmt(next(r for r in a['beta_rows'] if r['G']==g and r['beta']==beta)['A_star'])
                       if next(r for r in a['beta_rows'] if r['G']==g and r['beta']==beta)['A_star'] is not None else '均衡不可行'
                       for beta in [0.8,0.85,0.9,1.0]] for a in good for g in [2,3]])
text+='\n\n**表7-5b：共同上限 $\\beta=0.85$ 的分型配置与库存缺口。**\n\n'+table(
    ['快照','组数','基本单元分组','需求向量','缺口向量'],
    [[a['snapshot'],r['G'],code(r['partition_code']),vec(r['D']),vec(r['gaps'])]
     for a in good for r in a['beta_rows'] if r['beta']==0.85])
text+='\n\narchive_00、archive_01、archive_02的历史浮点容差核验通过，但严格保留JSON十进制时存在原实体交接重叠：前两者各2处、后者2处，量级为 $5\\times10^{-13}$—$10^{-12}$ s。这会使集中峰值错误增加，故本轮标为“输入精度待统一”并记录相邻任务与原始差值，未舍入、移动任务或写回第三问，也未把它们列为正式配置比较。该状态不是物理不可行或分区结构不可行的结论。主快照与表7-5中的其他快照不存在这一问题。'
block('**【表7-5占位：','**【图7-5占位：',text)
old='**【结果分析占位】** 备选【待填】与主方案在原运行目标上的差异为【待填】，其结构可分性及集中／独立资源需求变化为【待填】。这说明在已比较的有限方案中，运行表现与独立承担能力之间存在【待填】关系；不由少量方案宣称两者必然冲突。主分析仍保留预先指定的 $X^0$，本节不替换第7.2—7.3节结果。'
replace(old,'''在这4个通过严格检查的档案中，archive_05的总能耗最低、与archive_06并列具有最短联合完成时间，代价是比主方案多1个架次且加权迟到增加约137.285491 s。共同均衡上限0.85下，archive_03与archive_05两组负担为0.875000，低于主方案0.927083；对应分型配置减少A型机和电池，但三组又需要更多B型机与电池。该差异说明负担均值下降不等于所有类别缺口改善。archive_06虽然改变运行四目标，主方案对应的配置前沿及代表分组在展示精度下保持一致，说明运行指标变化不必引起资源峰值变化。各快照的遗憾值仅用于其自身分区选择，跨快照比较使用共同均衡上限和分型配置；主分析仍保留原定快照。''')
replace('2组和3组均可行。2组代表', '2组和3组均结构合法，但全部13种划分均超出部分现有库存，补配后才能独立执行。2组代表')
replace('3组增加了C型运输无人机和电池的独立配置，但没有降低中继资源需求。',
        '相对2组代表，3组仅增加1架C型运输无人机，运输电池及中继资源需求均相同；综合不均衡由0.768731升至0.826548。')
chapter=chapter.replace('基准可取 $\\delta_0=0.3$', '基准取 $\\delta_0=0.3$')
new=prefix+chapter
assert new.split('# 7 问题四',1)[0]==prefix
assert not any(ord(c)<32 and c not in '\n\r\t' for c in new)
PAPER.write_text(new,encoding='utf-8')
(HERE/'第7章_结果摘录.md').write_text(chapter.split('**本章引用与数据依据',1)[0],encoding='utf-8')
summary='''# 问题四求解结果

主输入为问题三精修主方案；冻结任务、时刻、能耗和实际保障关系，允许同型资源组内重匹配。原问题三文件未修改。

从实际通信恢复4个基本单元，完整枚举7个两组划分和6个三组划分。采用原双目标、ε约束、MILP与有效LP下界交叉核验，在各组数内以偏好权重区间[0.35,0.65]作最小最大遗憾选择。

'''
summary+=table(['组数','代表分区','$A$','$B$','八类资源需求','库存缺口'],[[g,code(s['partition_code']),fmt(s['A']),fmt(s['B']),vec(s['D']),vec(s['gaps'])] for g,s in sol.items()])
summary+='\n\n八类顺序：A/B/C运输机，A/B/C电池，中继机，中继组件。C1=S001，C3=S006，C4=S011；C2为其余12区。两组和三组均需要补配；全部划分中不存在同时满足原库存的方案。三组代表比两组多1架C型机，电池需求相同。\n\n'
summary+=f'独立核验：{audit["checks"]}项通过；包含96行资源分配见证、80箱和31箱硬时限继承、完整分区复算、提交表5行回读。双GPU分别完成112、80项峰值交叉检查。最优性仅针对冻结快照的分区模型，不是问题三全调度空间最优。\n\n'
summary+='主方案与3个备选完成相同口径比较；另3个备选有约10^-12 s的原资源交接误差，原值保留并标明精度待统一。\n\n文件入口：\n\n- `子问题一/问题四_结果提交.xlsx`：官方模板Q4页，仅两个选定代表的5个组。\n- `第7章_结果摘录.md`：已经回填正文的公式、结果表与分析。\n- `子问题一/分区枚举明细.csv`、`子问题一/非支配档案.csv`：完整划分和前沿。\n- `子问题二/组内资源分配见证.csv`、`子问题二/资源峰值证书.json`：最低数量的可执行资源匹配。\n- `子问题一/MILP与LP核验.json`、`子问题二/核验报告.json`：求解及独立核验记录。\n'
(HERE/'问题四求解结果.md').write_text(summary,encoding='utf-8')
print('Chapter 7 updated; previous chapters preserved. Report and chapter extract written.')
