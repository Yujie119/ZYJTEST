"""A logged ALNS move, probabilities and complete-objective traces."""
from plot_style import *

def main():
    data=DATA['alns'];fig,axs=plt.subplots(2,2,figsize=(12,7.0))
    fig.subplots_adjust(left=.075,right=.985,top=.88,bottom=.10,wspace=.26,hspace=.57)
    fixed=set(data['fixed']);released=set(data['released'])
    uavs=[f'U{i:02d}' for i in range(1,9)]
    for ax,plan,is_before,label in zip(axs[0],[data['before'],data['after']],[True,False],['(a)','(b)']):
        for r in plan['routes']:
            cid=r['candidate_id'];unchanged=cid in fixed
            color=GRAY if unchanged else ORANGE if is_before else BLUE
            ax.broken_barh([(r['start']/60,(r['finish']-r['start'])/60)],(uavs.index(r['uav'])-.32,.64),facecolors=color,
                edgecolors='white' if unchanged else color,lw=.5,alpha=.52 if unchanged else .9)
            if not unchanged:
                txt=r['zones'][0]+' / '+str(len(r['box_ids']))
                ax.text((r['start']+r['finish'])/120,uavs.index(r['uav']),txt,ha='center',va='center',fontsize=7.8,color='white')
        ax.set(xlim=(-2,157),ylim=(7.65,-.8),yticks=range(8),yticklabels=uavs,xlabel='准备开始至返场的时间区间 (min)')
        ax.text(.02,1.10,'释放前：20 架次，选中 3 架次' if is_before else '修复后：23 架次，局部 6 架次（2 沿用 + 4 新增）',transform=ax.transAxes,fontsize=9.8)
        panel(ax,label)
        if not is_before:
            ax.annotate('4 个 A 型架次\n提前配送 S001',xy=(26,1.67),xytext=(55,1),fontsize=9,color=BLUE,
                arrowprops=dict(arrowstyle='->',color=BLUE,lw=.8))
    axs[0,0].annotate('被释放的晚段任务',xy=(139,6.67),xytext=(62,6.3),fontsize=9,color=ORANGE,
        arrowprops=dict(arrowstyle='->',color=ORANGE,lw=.8))
    bx,cx=axs[1];log=data['log'];x=np.arange(1,len(log)+1);probs=np.array([r['probabilities'] for r in log])
    for j,(name,color,ls) in enumerate(zip(['随机','时限压力','充电时长','能耗'],[BLUE,ORANGE,GREEN,PURPLE],['-','--','-.',':'])):
        bx.step(x,probs[:,j],where='post',label=name,color=color,ls=ls,lw=1.45)
        selected=[i+1 for i,r in enumerate(log) if r['operator']==['random','deadline','battery','energy'][j]]
        bx.scatter(selected,[probs[k-1,j] for k in selected],s=17,color=color,zorder=5)
    bx.set(xlim=(.6,15.5),ylim=(.08,.66),xticks=[1,3,6,9,12,15],xlabel='ALNS 迭代次数',ylabel='本次选择前的算子概率')
    bx.legend(loc='upper left',frameon=False,ncol=2,fontsize=8.8);panel(bx,'(c)')
    bx.annotate('第 10、11 次随机算子获奖励\n第 12 次后提高其概率',xy=(13,probs[12,0]),xytext=(5.5,.45),fontsize=8.8,
        arrowprops=dict(arrowstyle='->',color=BLUE,lw=.8),color=BLUE)
    states=np.array(data['states']);norm=states/states[0];steps=np.arange(len(states))
    for j,(symbol,color,ls) in enumerate(zip(['$N/N_0$','$E/E_0$',r'$C_{\max}/C_0$','$L/L_0$'],[INK,GREEN,BLUE,ORANGE],[':', '-.', '-', '--'])):
        cx.step(steps,norm[:,j],where='post',label=symbol,color=color,ls=ls,lw=1.4)
    accepted=[i+1 for i,r in enumerate(log) if r['accepted']]
    for t in accepted:cx.axvline(t,color='#CFD5DA',lw=.7,zorder=0)
    cx.scatter(accepted,norm[accepted,3],color=ORANGE,marker='x',s=40,zorder=5)
    cx.set(xlim=(0,15.5),ylim=(0,1.33),xticks=[0,3,6,9,12,15],xlabel='已完成迭代次数（0 为初始解）',ylabel='相对初始值（越小越好）')
    cx.legend(loc='lower left',frameon=False,ncol=2,fontsize=9);panel(cx,'(d)')
    cx.text(.03,.95,'接受发生于第 10、11、13 次\n架次与能耗增加，换取时间与迟到改善',transform=cx.transAxes,va='top',fontsize=9.2)
    fig.legend(handles=[Patch(facecolor=GRAY,alpha=.52,label='未释放的 17 架次，时刻与资源固定'),
        Patch(facecolor=ORANGE,label='被释放架次'),Patch(facecolor=BLUE,label='局部修复结果；条内为服务区 / 箱数')],
        loc='upper center',bbox_to_anchor=(.53,1.01),ncol=3,frameon=False)
    save(fig,'图3_ALNS破坏修复与自适应算子')

if __name__=='__main__':main()
