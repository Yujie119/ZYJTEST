"""Conditional filtering of 14 verified schedules, not a complete feasible set."""
from plot_style import *

def main():
    F=objectives();fig,axes=plt.subplots(1,3,figsize=(12.6,4.1),sharex=True,sharey=True)
    fig.subplots_adjust(left=.075,right=.99,bottom=.24,top=.79,wspace=.14)
    for j,(ax,rec) in enumerate(zip(axes,DATA['epsilon_filters'])):
        cap=rec['cap'];ok=np.zeros(len(F),bool);ok[rec['eligible']]=True;choice=rec['selected']
        ax.axvspan(59.6,cap['E'],color=BLUE,alpha=.10)
        ax.axvline(cap['E'],color=BLUE,ls=(0,(4,3)),lw=1.1)
        ax.scatter(F[~ok,1],F[~ok,2]/60,s=31,facecolors='white',edgecolors='#949CA2',lw=.9,zorder=3)
        ax.scatter(F[ok,1],F[ok,2]/60,s=34,color=INK,zorder=4)
        ax.scatter(F[choice,1],F[choice,2]/60,s=110,marker='x',color=BLUE,lw=2,zorder=6)
        ax.annotate(f"PF{choice+1:04d}\n{int(F[choice,0])} 架次 · {F[choice,2]/60:.3f} min",
            (F[choice,1],F[choice,2]/60),xytext=(-8,21),textcoords='offset points',ha='right',color=BLUE,fontsize=9.5,
            arrowprops={'arrowstyle':'-','lw':.65,'color':BLUE})
        ax.text(.97,.95,rf'$N\leq {cap["N"]}$'+'\n'+rf'$E\leq {cap["E"]:g}$ kWh'+'\n'+rf'$L\leq {cap["L"]:g}$ s',
            transform=ax.transAxes,ha='right',va='top',linespacing=1.55,fontsize=10,
            bbox=dict(facecolor='white',edgecolor='none',alpha=.9,pad=2))
        ax.text(.5,-.25,f'档案保留 {len(rec["eligible"])} / 14 个方案',transform=ax.transAxes,ha='center',fontsize=10)
        ax.set(xlim=(59.6,71.4),ylim=(96,164),xlabel='总能耗 $E$ (kWh)',xticks=[60,64,68,71])
        panel(ax,f'({chr(97+j)})')
        ax.annotate('',xy=(70.5,106),xytext=(70.5,126),arrowprops=dict(arrowstyle='->',color=INK,lw=1.1))
        ax.text(70.2,129,r'$\min C_{\max}$',ha='right',fontsize=10)
    axes[0].set_ylabel(r'最晚返场 $C_{\max}$ (min)')
    axes[1].text(.96,.57,'收紧迟到上限\n最早点保持不变',transform=axes[1].transAxes,fontsize=9.4,color=GREEN,ha='right')
    fig.legend(handles=[Line2D([],[],marker='o',ls='',mfc='white',mec='#949CA2',label='被 ε 排除的已知方案'),
        Line2D([],[],marker='o',ls='',color=INK,label='通过 N / E / L 筛选'),
        Line2D([],[],marker='x',ls='',color=BLUE,label='档案内最早返场'),
        Patch(facecolor=BLUE,alpha=.10,label='仅表示 E 上限半平面')],loc='upper center',ncol=4,bbox_to_anchor=(.53,1.015),frameon=False)
    save(fig,'图1_epsilon约束与四目标条件筛选')

if __name__=='__main__':main()
