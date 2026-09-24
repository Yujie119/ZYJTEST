"""Actual incidence + conceptual removal, actual post-update operator weights."""
from plot_style import *
def main():
    fig=plt.figure(figsize=(13.2,8.2));gs=fig.add_gridspec(2,2,left=.055,right=.975,top=.93,bottom=.12,wspace=.27,hspace=.52,height_ratios=[1.2,1])
    dx=fig.add_subplot(gs[0,0]);ax=fig.add_subplot(gs[0,1]);bx=fig.add_subplot(gs[1,0]);cx=fig.add_subplot(gs[1,1])
    dx.set(xlim=(0,1),ylim=(0,1));dx.axis('off');panel(dx,'(a)')
    dx.add_patch(Polygon([[.04,.24],[.08,.64],[.31,.88],[.78,.84],[.95,.51],[.88,.22],[.50,.13]],closed=True,fc=GRAY,ec=GRAY,alpha=.22))
    dx.add_patch(Ellipse((.51,.43),.51,.35,angle=12,fc=BLUE,ec=BLUE,alpha=.15))
    dx.text(.17,.73,r'$\mathcal{X}_{\mathrm{cert}}$：固定模型的完整可行解集',fontsize=10)
    dx.text(.47,.61,r'$\mathcal{N}_D(x_t)$：关联破坏定义的邻域',ha='center',fontsize=10,color=BLUE)
    dx.scatter([.15,.24,.80,.82,.46],[.38,.65,.70,.40,.78],s=23,color=GRAY)
    dx.scatter(.38,.34,s=60,color=BLUE,zorder=4);dx.scatter(.68,.46,s=65,marker='D',color=ORANGE,zorder=4)
    arrow(dx,(.42,.355),(.635,.438),ORANGE)
    dx.text(.35,.245,r'$x_t$：当前方案',ha='center',fontsize=10,color=BLUE)
    dx.text(.74,.345,r'$y$：修复候选',ha='center',fontsize=10,color=ORANGE)
    dx.text(.50,.015,'冻结未释放决策，重新联合优化运输与中继\n纯机理示意；几何位置、边界和候选点均无实测含义',ha='center',fontsize=9.2,linespacing=1.5)
    ax.set(xlim=(0,1),ylim=(0,1));ax.axis('off');panel(ax,'(b)')
    graph=DATA['graph'];nodes=graph['routes'];ys=np.linspace(.83,.32,len(nodes))
    ax.add_patch(Rectangle((.64,.56),.32,.17,fc='#EDF2F5',ec=ORANGE,lw=1.3))
    ax.text(.80,.645,graph['relay'],ha='center',va='center',color=ORANGE,fontsize=12)
    for y,r in zip(ys,nodes):
        color=ORANGE if r['related'] else GRAY
        ax.add_patch(Rectangle((.01,y-.035),.37,.07,fc='white',ec=color,lw=1))
        ax.text(.195,y,r['id']+' · '+r['zone'],ha='center',va='center',fontsize=8.2,color=INK)
        if r['related']:ax.plot([.38,.64],[y,.645],color=ORANGE,lw=1,ls='--')
    ax.text(.5,.95,'运输—中继关联释放：真实关联 + 示意操作',ha='center',fontsize=11)
    shown=sum(r['related'] for r in nodes);total=graph['incidence_count']
    ax.text(.03,.09,f'虚线：全部 {total} 条关联中的 {shown} 条摘录；另 {total-shown} 条省略\n橙色：释放示例；实际修复须覆盖全部受影响关系',fontsize=9.2,linespacing=1.6)
    panel(bx,'(c)');bx.set(xlim=(0,1),ylim=(0,1));bx.axis('off')
    labels=['选择\n算子','关联\n破坏','联合 MILP\n修复','完整\n核验','档案／权重\n更新']
    x=np.linspace(.09,.91,5)
    for k,(xx,label) in enumerate(zip(x,labels)):
        bx.add_patch(Rectangle((xx-.078,.45),.156,.26,fc='white',ec=ORANGE if k==1 else BLUE,lw=1))
        bx.text(xx,.58,label,ha='center',va='center',fontsize=9)
        if k<4:arrow(bx,(xx+.079,.58),(x[k+1]-.079,.58),BLUE)
    bx.annotate('',xy=(x[0],.75),xytext=(x[-1],.75),arrowprops=dict(arrowstyle='->',connectionstyle='arc3,rad=.22',color=BLUE,lw=1))
    bx.text(.5,.19,'修复约束：箱组覆盖、机体／电池先后\n中继赴返与服务、连续通信',ha='center',fontsize=9.5,linespacing=1.5)
    bx.text(.5,-.03,'规范流程示意；未通过完整核验的候选不得入可行档案',ha='center',fontsize=9.2)
    chain=DATA['chains'][0];rows=chain['rows'];w=np.array([r['operator_weights'] for r in rows]);prob=w/w.sum(1,keepdims=True)
    for j,(name,color,ls) in enumerate(zip(['随机移除','通信需求','单位货箱能耗','中继关联'],[BLUE,ORANGE,GREEN,PURPLE],['-','--','-.',':'])):
        cx.step(range(1,9),prob[:,j],where='post',label=name,color=color,ls=ls,lw=1.5)
        cx.scatter(range(1,9),prob[:,j],color=color,s=13)
    cx.set(xlim=(.8,8.2),ylim=(.16,.33),xticks=range(1,9),xlabel='历史链 202631：已完成迭代次数',ylabel='更新后权重归一化')
    cx.legend(frameon=False,ncol=2,loc='upper left',fontsize=9)
    cx.text(.5,-.37,'真实日志：更新后 w / Σw\n第5次为全局资源重排；此处不绘制虚构的目标收敛曲线',ha='center',transform=cx.transAxes,fontsize=9.2)
    panel(cx,'(d)')
    save(fig,'图3_ALNS关联破坏修复与算子自适应')
if __name__=='__main__':main()
