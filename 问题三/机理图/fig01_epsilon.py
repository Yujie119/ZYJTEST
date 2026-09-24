"""Posthoc conditional filtering of six verified nondominated archive vectors."""
from plot_style import *
def main():
    F=objectives();fig,axs=plt.subplots(1,3,figsize=(13.4,4.4),sharex=True,sharey=True)
    fig.subplots_adjust(left=.065,right=.99,bottom=.24,top=.79,wspace=.15)
    for j,(ax,rec) in enumerate(zip(axs,DATA['filters'])):
        cap=rec['caps'];selected=rec['best'];eligible=rec['eligible']
        ax.add_patch(Rectangle((64.55,430),cap['E']-64.55,cap['L']-430,fc=BLUE,alpha=.10,lw=0))
        ax.axvline(cap['E'],color=BLUE,ls='--',lw=1)
        ax.axhline(cap['L'],color=BLUE,ls='--',lw=1)
        for i,(f,r) in enumerate(zip(F,DATA['archive'])):
            good=i in eligible
            ax.scatter(f[1],f[3],s=46,marker='o' if f[0]==24 else 's',facecolors=INK if good else 'white',edgecolors=INK if good else GRAY,zorder=4)
            offsets={'CA01':(-7,12,'right'),'CA03':(7,11,'left'),
                     'CA04':(8,-17,'left'),'CA05':(-7,12,'right'),
                     'CA06':(0,12,'center'),'CA07':(-7,-17,'right')}
            dx,dy,ha=offsets[r['id']]
            ax.annotate(r['id'],(f[1],f[3]),xytext=(dx,dy),textcoords='offset points',ha=ha,fontsize=8,color=INK if good else '#737D84')
        if selected is not None:
            f=F[selected];ax.scatter(f[1],f[3],marker='x',s=170,color=BLUE,lw=2.2,zorder=6)
            text=f"{DATA['archive'][selected]['id']}：档案内最早返场\n"+rf'$C^{{joint}}={f[2]:.3f}$ s'
        else:text='档案中没有满足阈值的方案\n不能据此判定原模型不可行'
        ax.text(.03,.53,text,transform=ax.transAxes,fontsize=9.5,color=BLUE,va='center',bbox=dict(fc='white',ec='none',alpha=.9,pad=2))
        ax.text(.97,.95,f"N ≤ {cap['N']}\nE ≤ {cap['E']:.2f} kWh\nL ≤ {cap['L']} s",ha='right',va='top',transform=ax.transAxes,fontsize=9.5,
                bbox=dict(fc='white',ec='none',alpha=.9,pad=3))
        ax.set(xlim=(64.55,65.25),ylim=(430,690),xticks=[64.6,64.8,65,65.2],xlabel=r'总能耗 $E=E_T+E_R$ (kWh)')
        ax.text(.5,-.26,f'通过三项 ε 筛选：{len(eligible)} / 6',ha='center',transform=ax.transAxes)
        panel(ax,f'({chr(97+j)})')
    axs[0].set_ylabel(r'加权迟到 $L$ (s)')
    fig.legend(handles=[Line2D([],[],marker='o',color=INK,ls='',label='N=24'),Line2D([],[],marker='s',color=INK,ls='',label='N=25'),
      Line2D([],[],marker='o',mfc='white',mec=GRAY,ls='',label='被阈值排除'),Line2D([],[],marker='x',color=BLUE,ls='',label='条件档案代表'),
      Patch(fc=BLUE,alpha=.12,label='E / L 阈值交集；另筛选 N')],loc='upper center',bbox_to_anchor=(.52,1.01),ncol=5,frameon=False)
    save(fig,'图1_epsilon约束与联合目标条件筛选')
if __name__=='__main__':main()
