"""Separate global LP gaps from certified zero minimax-regret bound."""
from plot_style import *

def main():
    fig,axes=plt.subplots(1,3,figsize=(10.5,3.45))
    fig.subplots_adjust(wspace=.24,bottom=.27,top=.90,left=.065,right=.96)
    labels=['架次数 $N$','总能耗 $E$ (kWh)','总作业时间 $T$ ($10^3$ s)']
    for j,(ax,b) in enumerate(zip(axes,DATA['bounds'])):
        div=1000 if j==2 else 1
        values=np.array([b['LP_lower'],b['integer_optimum'],b['final_value']])/div
        ax.plot(values,[2,1,0],color='#ABB3B9',lw=1,zorder=1)
        for x,y,marker,color in zip(values,[2,1,0],['D','s','x'],[ORANGE,INK,BLUE]):
            ax.scatter(x,y,s=65,marker=marker,color=color,zorder=3)
            ax.annotate(f'{x:.4f}',(x,y),xytext=(0,10),textcoords='offset points',ha='center',color=color,fontsize=10)
        span=values.max()-values.min()
        ax.set(xlim=(values.min()-.23*span,values.max()+.23*span),ylim=(-.5,2.6),
            yticks=[0,1,2],yticklabels=['综合方案','单目标整数最优','LP 下界'] if j==0 else [],xlabel=labels[j])
        ax.ticklabel_format(axis='x',useOffset=False)
        ax.text(.5,-.33,rf'$(f_{{A}}-L)/f_{{A}}={b["final_gap_pct"]:.2f}\%$',ha='center',transform=ax.transAxes,fontsize=11)
        panel(ax,f'({chr(97+j)})')
    save(fig,'图4_全局连续松弛下界核验')

if __name__=='__main__':main()
