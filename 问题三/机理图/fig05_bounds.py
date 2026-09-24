"""Old matched finite-model brackets and new-library lower bounds kept separate."""
from plot_style import *
def main():
    fig,(ax,bx)=plt.subplots(1,2,figsize=(12.2,4.7),gridspec_kw={'width_ratios':[1.05,1.05]})
    fig.subplots_adjust(left=.11,right=.975,bottom=.24,top=.81,wspace=.4)
    for i,r in enumerate(DATA['old_bounds']):
        lb=r['lower_bound'];ub=r['external_witness_upper_bound'];z=lb/ub
        ax.plot([z,1],[i,i],color=GRAY,lw=6,solid_capstyle='butt',zorder=1)
        ax.scatter(z,i,marker='D',s=40,color=ORANGE,zorder=3);ax.scatter(1,i,marker='o',s=40,color=BLUE,zorder=3)
        ax.text(.99,i-.14,f"LB={lb:.3f}   UB={ub:.3f}",ha='right',fontsize=8.8)
        ax.text(1.055,i,f"{r['relative_gap']*100:.2f}%",va='center',fontsize=9.2)
    ax.set(yticks=range(4),yticklabels=['C (s)','E (kWh)','L (s)','N (架次)'],ylim=(3.5,-.65),xlim=(-.03,1.24),
           xticks=[0,.25,.5,.75,1],xlabel='各自子问题的目标值 / 已核验外部上界')
    ax.text(.5,1.05,'1445 实例库；各行 ε 条件分别冻结',transform=ax.transAxes,ha='center',fontsize=10)
    ax.text(.5,-.29,'见证满足每行阈值并已完成模型映射\n界差属于对应标量子问题，不能合成多目标最优证书',transform=ax.transAxes,ha='center',fontsize=9.3)
    panel(ax,'(a)')
    run=next(r for r in DATA['long_runs'] if r['scalar_objective']=='C')
    t=0;times=[];best=[];current=None;marks=[]
    for row in run['iterations']:
        t+=row['elapsed_s'];lb=row.get('dual_bound')
        if lb is not None:current=lb if current is None else max(current,lb)
        if current is not None:times.append(t/60);best.append(current/60)
        if row.get('incumbent_available') and not row.get('accepted_as_feasible'):
            marks.append((t/60,(row.get('dual_bound') or current)/60))
    bx.step(times,best,where='post',color=ORANGE,lw=1.8)
    bx.scatter(times,best,color=ORANGE,s=30,marker='D',zorder=4)
    # Status symbols have an axes-coordinate height, never an objective value.
    for x,y in marks:bx.plot(x,.075,marker='x',color=INK,ms=6,transform=bx.get_xaxis_transform())
    bx.annotate(f"最终有效下界\n{run['finite_model_valid_lower_bound']:.3f} s",xy=(times[-1],best[-1]),xytext=(55,106.0),fontsize=10,color=ORANGE,
                arrowprops=dict(arrowstyle='->',color=ORANGE,lw=.8))
    bx.text(.05,.93,'本轮未得到完整核验的上界\n不绘制“收敛到最优”或上下界闭合',va='top',transform=bx.transAxes,fontsize=9.5)
    bx.set(xlim=(0,125),ylim=(104.8,110.5),xlabel='累计子问题求解时间 (min)',ylabel=r'联合完成时间下界 (min)')
    bx.text(.5,1.05,'1596 实例库；两小时 C 子问题',transform=bx.transAxes,ha='center',fontsize=10)
    bx.text(.5,-.29,'底部 ×：曾返回不完整松弛解的轮次\n状态标记不对应纵轴目标值',transform=bx.transAxes,ha='center',fontsize=9.3)
    panel(bx,'(b)')
    fig.legend(handles=[Line2D([],[],marker='D',color=ORANGE,label='有效下界'),Line2D([],[],marker='o',ls='',color=BLUE,label='已核验外部上界（仅左图）')],loc='upper center',bbox_to_anchor=(.53,1.015),ncol=2,frameon=False)
    save(fig,'图5_同域界差与扩库后的下界进展')
if __name__=='__main__':main()
