"""Matched-condition primal/relaxation bounds and preference regret intervals."""
from plot_style import *

def main():
    fig,(ax,bx)=plt.subplots(1,2,figsize=(11.8,4.5),gridspec_kw={'width_ratios':[1.16,1]})
    fig.subplots_adjust(left=.115,right=.98,top=.82,bottom=.18,wspace=.37)
    names=['不附加 N / E 上限',r'$N\leq20$',r'$N\leq21$',r'$N\leq22$',r'$N\leq22,\ E\leq66$']
    for i,r in enumerate(DATA['bounds']):
        l,u=r['lower_min'],r['upper_min'];ax.plot([l,u],[i,i],color=GRAY,lw=2)
        ax.scatter(l,i,marker='D',s=44,color=ORANGE,zorder=4);ax.scatter(u,i,marker='s',s=40,color=INK,zorder=4)
        ax.text(l,i-.17,f'{l:.3f}',ha='center',fontsize=9,color=ORANGE)
        ax.text(u,i+.26,f'{u:.3f}',ha='center',fontsize=9,color=INK)
    ax.set(yticks=range(5),yticklabels=names,ylim=(4.65,-.65),xlim=(86.5,118.7),xlabel='最晚返场 $C$ (min)')
    ax.text(DATA['final_objective'][2]/60+.4,4.52,'此行上界为最终 22 架次方案',fontsize=8.8,color=BLUE)
    panel(ax,'(a)')
    for i,r in enumerate(DATA['preferences']):
        l,u=r['regret_lower'],r['regret_upper'];bx.plot([l,u],[i,i],color=GRAY,lw=1.7)
        bx.scatter(l,i,color=INK,s=19,marker='o');bx.scatter(u,i,color=ORANGE,s=25,marker='D')
    lower,upper=DATA['final_regret'];bx.axvline(lower,color=BLUE,ls=':',lw=1.1);bx.axvline(upper,color=ORANGE,ls='--',lw=1.1)
    bx.set(ylim=(11.8,-1.0),xlim=(-.012,.23),yticks=range(12),yticklabels=[f'$w^{{({i+1})}}$' for i in range(12)],
        xlabel='最终方案相对于该偏好最优基准的遗憾界')
    bx.text(.03,-.34,rf'$\max_h r_h^-= {lower:.6f}$'+'    '+rf'$\max_h r_h^+= {upper:.6f}$',transform=bx.transAxes,fontsize=10,color=BLUE)
    panel(bx,'(b)')
    ax.legend(handles=[Line2D([],[],color=ORANGE,marker='D',ls='',label='同条件 LP 下界'),
        Line2D([],[],color=INK,marker='s',ls='',label='同条件档案最早可行值')],loc='upper center',bbox_to_anchor=(.48,1.27),frameon=False,ncol=2,fontsize=9)
    bx.legend(handles=[Line2D([],[],color=INK,marker='o',ls='',label=r'$r_h^-=\phi_h(X)-UB_h$'),
        Line2D([],[],color=ORANGE,marker='D',ls='',label=r'$r_h^+=\phi_h(X)-LB_h$')],loc='upper center',bbox_to_anchor=(.49,1.27),frameon=False,ncol=1,fontsize=9)
    save(fig,'图5_同条件下界与最坏遗憾区间')

if __name__=='__main__':main()
