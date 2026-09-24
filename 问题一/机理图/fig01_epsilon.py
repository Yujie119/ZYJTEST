"""True conditional feasible points, epsilon cut, and an enlarged tradeoff."""
from plot_style import *

def main():
    fs=np.asarray(DATA['slice_objectives'])
    A,B=front()
    cap=B[2]-.001
    fig,(ax,bx)=plt.subplots(1,2,figsize=(10.2,4.0),gridspec_kw={'width_ratios':[1.35,1]})
    fig.subplots_adjust(wspace=.32,bottom=.20,top=.86)
    left,right=fs[:,1].min()-.35,fs[:,1].max()+.4
    bottom,top=fs[:,2].min()/1000-.5,fs[:,2].max()/1000+.6
    ax.add_patch(Rectangle((left,bottom),right-left,cap/1000-bottom,
        facecolor=BLUE,alpha=.13,edgecolor='none'))
    ok=(fs[:,0]<=19)&(fs[:,2]<=cap+1e-8)
    ax.scatter(fs[~ok,1],fs[~ok,2]/1000,s=21,facecolor='white',edgecolor='#777E83',lw=.8)
    ax.scatter(fs[ok,1],fs[ok,2]/1000,s=27,c=INK,zorder=5)
    ax.axhline(cap/1000,color=BLUE,ls=(0,(4,3)),lw=1.1)
    ax.scatter(A[1],A[2]/1000,s=90,marker='x',color=BLUE,lw=1.8,zorder=6)
    ax.annotate('$A$: PF001',(A[1],A[2]/1000),xytext=(21,4),textcoords='offset points',color=BLUE)
    ax.annotate('$B$: PF002',(B[1],B[2]/1000),xytext=(14,12),textcoords='offset points',
        arrowprops={'arrowstyle':'-','color':INK,'lw':.65})
    ax.text(right-.12,cap/1000+.17,r'$\varepsilon_T=T_B-0.001\ \mathrm{s}$',ha='right',color=BLUE)
    ax.annotate('',xy=(left+2.8,bottom+.40),xytext=(left+4.3,bottom+.40),
        arrowprops={'arrowstyle':'->','color':INK})
    ax.text(left+3.55,bottom+.56,r'$\min E$',ha='center')
    ax.set(xlim=(left,right),ylim=(bottom,top),xlabel='总能耗 $E$ (kWh)',ylabel='总作业时间 $T$ ($10^3$ s)')
    panel(ax,'(a)')
    ax.text(.02,.97,'S008 条件可行集：36 个整数组批方案',transform=ax.transAxes,va='top',fontsize=10)
    bx.set(xlim=(B[1]-.028,A[1]+.028),ylim=(A[2]/1000-.4,B[2]/1000+.4),
        xlabel='总能耗 $E$ (kWh)',ylabel='总作业时间 $T$ ($10^3$ s)')
    bx.add_patch(Rectangle((B[1]-.028,A[2]/1000-.4),A[1]-B[1]+.056,
        cap/1000-(A[2]/1000-.4),facecolor=BLUE,alpha=.13,edgecolor='none'))
    bx.axhline(cap/1000,color=BLUE,ls=(0,(4,3)),lw=1.1)
    bx.scatter(B[1],B[2]/1000,s=65,facecolor='white',edgecolor=ORANGE,lw=1.6,zorder=5)
    bx.scatter(A[1],A[2]/1000,s=95,marker='x',color=BLUE,lw=1.8,zorder=5)
    bx.text(B[1]+.007,B[2]/1000+.09,'$B$：19 架次',color=ORANGE)
    bx.text(A[1]-.007,A[2]/1000-.24,'$A$：18 架次',color=BLUE,ha='right')
    bx.plot([B[1],A[1]],[A[2]/1000,A[2]/1000],color=INK,ls=':',lw=.9)
    bx.plot([B[1],B[1]],[A[2]/1000,B[2]/1000],color=INK,ls=':',lw=.9)
    bx.text((A[1]+B[1])/2,(A[2]+B[2])/2000,
        rf'$\Delta E={A[1]-B[1]:.6f}$ kWh'+'\n'+rf'$\Delta T={B[2]-A[2]:.3f}$ s',ha='center',va='center',linespacing=1.7)
    bx.ticklabel_format(axis='x',useOffset=False)
    bx.set_xticks([59.04,59.08,59.12])
    panel(bx,'(b)')
    fig.legend(handles=[Line2D([],[],marker='o',linestyle='',mfc='white',mec='#777E83',label='被 ε 上限排除的可行方案'),
        Line2D([],[],marker='x',linestyle='',color=BLUE,label='ε 子问题最优解'),
        Rectangle((0,0),1,1,facecolor=BLUE,alpha=.13,label='满足时间上限的搜索半平面')],
        loc='upper center',bbox_to_anchor=(.51,1.015),ncol=3,frameon=False)
    save(fig,'图1_epsilon约束与条件可行集')

if __name__=='__main__': main()
