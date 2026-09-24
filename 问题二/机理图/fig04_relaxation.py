"""Certified LP projection versus known feasible schedules; no invented hull."""
from plot_style import *

def main():
    p=DATA['projection'];F=objectives();fig,(ax,bx)=plt.subplots(1,2,figsize=(11.7,4.65),gridspec_kw={'width_ratios':[1.35,1]})
    fig.subplots_adjust(left=.085,right=.97,top=.80,bottom=.17,wspace=.38)
    poly=np.array(p['vertices']);hull=np.array(p['known_hull']);lp=np.array(p['min_c_point'])
    ax.add_patch(Polygon(poly,facecolor=GRAY,edgecolor='none',alpha=.60))
    for a,b in zip(poly,np.roll(poly,-1,axis=0)):
        clipped=any(abs(a[d]-v)<1e-6 and abs(b[d]-v)<1e-6 for d,v in [(0,58),(0,72),(1,85),(1,160)])
        ax.plot([a[0],b[0]],[a[1],b[1]],color='#7A8790' if clipped else INK,ls=':' if clipped else '-',lw=.9 if clipped else 1.2)
    ax.add_patch(Polygon(hull,facecolor='white',edgecolor=INK,hatch='////',lw=.8,alpha=.90))
    ax.scatter(F[:,1],F[:,2]/60,marker='s',facecolors='white',edgecolors=INK,s=27,zorder=5,lw=.9)
    best=int(np.argmin(F[:,2]));ax.scatter(F[best,1],F[best,2]/60,color=BLUE,marker='x',s=80,lw=1.8,zorder=7)
    ax.scatter(lp[0],lp[1],color=ORANGE,marker='D',s=65,zorder=7)
    ax.annotate(f'LP：{lp[1]:.3f} min',xy=lp,xytext=(60.8,86.8),fontsize=10,color=ORANGE,
        arrowprops=dict(arrowstyle='-',color=ORANGE,lw=.9))
    ax.annotate(f'档案最早：{F[best,2]/60:.3f} min',xy=(F[best,1],F[best,2]/60),xytext=(66.6,115),fontsize=9.5,color=BLUE,
        arrowprops=dict(arrowstyle='-',color=BLUE,lw=.8))
    ax.text(.09,1.03,'28,216 条候选；80 个逐箱覆盖等式',transform=ax.transAxes,va='bottom',fontsize=9.5)
    ax.set(xlim=(58,72.4),ylim=(83,164),xlabel='总能耗 $E$ (kWh)',ylabel=r'松弛辅助工期 $\widehat C$ / 实际 $C_{\max}$ (min)')
    ax.axhline(160,color='#7A8790',ls=':',lw=.8);ax.axvline(72,color='#7A8790',ls=':',lw=.8)
    panel(ax,'(a)')
    fractions=p['fractionals'][:9];vals=[r['value'] for r in fractions];idx=np.arange(len(vals))
    bx.barh(idx,vals,color=ORANGE,alpha=.82,height=.56)
    for i,(r,v) in enumerate(zip(fractions,vals)):bx.text(v+.025,i,f'{v:.4f}',va='center',fontsize=9,color=ORANGE)
    bx.set(yticks=idx,yticklabels=[f'{r["vehicle"]} · '+ '/'.join(r['zones']) for r in fractions],xlim=(0,1.20),
        ylim=(len(vals)-.3,-1.6),xlabel=r'松弛选取量 $x_k\in[0,1]$')
    bx.axvline(1,color=INK,ls=':',lw=.9)
    bx.text(.02,.98,f'最小工期 LP：{p["fractional_count"]} 条分数路线\n此处列出其中 9 条',transform=bx.transAxes,va='top',fontsize=9.5)
    bx.text(.98,-.26,'分数覆盖满足等式，但不能执行为实际架次',transform=bx.transAxes,ha='right',fontsize=9.5,color=ORANGE)
    panel(bx,'(b)')
    fig.legend(handles=[Patch(facecolor=GRAY,alpha=.6,edgecolor=INK,label='覆盖 + 机型工作量 LP 投影'),
        Patch(facecolor='white',edgecolor=INK,hatch='////',label='14 个已知方案投影的凸包'),
        Line2D([],[],marker='s',mfc='white',mec=INK,ls='',label='实际可行方案')],loc='upper center',bbox_to_anchor=(.52,1.01),ncol=3,frameon=False)
    save(fig,'图4_覆盖工作量松弛域与分数解')

if __name__=='__main__':main()
