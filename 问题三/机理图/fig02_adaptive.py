"""Adaptive target boxes are schematic; thresholds and 64 solver states are logged."""
from plot_style import *
from matplotlib.colors import ListedColormap
def main():
    fig,axs=plt.subplots(1,3,figsize=(13.2,4.8),gridspec_kw={'width_ratios':[1,1.1,1.25]})
    fig.subplots_adjust(left=.055,right=.96,bottom=.24,top=.83,wspace=.42)
    ax,bx,cx=axs
    ax.set(xlim=(0,1),ylim=(0,1),xlabel=r'阈值坐标 $\varepsilon_E$',ylabel=r'阈值坐标 $\varepsilon_L$',xticks=[],yticks=[])
    for x,y,w,h,c in [(.08,.08,.42,.38,GRAY),(.5,.08,.40,.38,BLUE),(.08,.46,.42,.44,ORANGE),(.5,.46,.40,.44,GRAY)]:
        ax.add_patch(Rectangle((x,y),w,h,fc=c,alpha=.10,ec=INK,lw=1))
    ax.plot([.5,.5],[.08,.9],color=INK,lw=.8);ax.plot([.08,.9],[.46,.46],color=INK,lw=.8)
    ax.scatter([.5],[.46],marker='x',s=90,color=BLUE,lw=2,zorder=5)
    ax.text(.29,.67,'下一待探索区域',ha='center',fontsize=9.5,color=ORANGE)
    ax.text(.70,.27,'当前 ε 子问题',ha='center',fontsize=9.5,color=BLUE)
    arrow(ax,(.62,.43),(.42,.58),ORANGE)
    ax.text(.5,-.27,'区域细分为机理示意\n'+r'固定 $\varepsilon_N$；盒内未必存在可行解',ha='center',transform=ax.transAxes,fontsize=9.4)
    panel(ax,'(a)')
    ch=DATA['chains'];cap1=[c['caps'] for c in ch if c['wave']==0];cap2=[c['caps'] for c in ch if c['wave']==1]
    es=np.array([[c['E'] for c in cap1],[c['E'] for c in cap2]])
    for j,col in enumerate([BLUE,ORANGE,GREEN,PURPLE]):
        bx.plot([0,1],es[:,j],marker='o',color=col,lw=1.5,label=f'情景 {j+1}')
        bx.text(1.08,es[1,j],f"N≤{cap2[j]['N']:.0f}\nL≤{cap2[j]['L']:.2f}",fontsize=8.7,color=col,va='center')
    bx.set(xlim=(-.15,1.7),ylim=(64.4,67.25),xticks=[0,1],xticklabels=['第1波','第2波'],ylabel=r'实际能耗阈值 $\varepsilon_E$ (kWh)')
    bx.annotate(f"中点更新 {es[0,1]:.5f}\n→ {es[1,1]:.5f}",xy=(.7,es[1,1]),xytext=(.06,65.17),fontsize=8.7,color=ORANGE,
                arrowprops=dict(arrowstyle='-',color=ORANGE,lw=.8))
    bx.text(.5,-.27,'真实历史阈值；仅能耗侧重情景变化\n其余阈值不变，不代表搜索完备',ha='center',transform=bx.transAxes,fontsize=9.4)
    panel(bx,'(b)')
    states=np.array([[int(r['feasible']) for r in c['rows']] for c in ch])
    cx.imshow(states,cmap=ListedColormap(['#F1F3F4',BLUE]),vmin=0,vmax=1,aspect='auto',interpolation='nearest')
    for i in range(8):
        for j in range(8):
            cx.text(j,i,'●' if states[i,j] else '×',color='white' if states[i,j] else '#9AA5AD',ha='center',va='center',fontsize=10)
    cx.set(xticks=range(8),xticklabels=range(1,9),yticks=range(8),yticklabels=[str(c['seed']) for c in ch],xlabel='链内迭代次数',ylabel='历史随机链种子')
    cx.axhline(3.5,color=INK,lw=1.4)
    cx.text(.5,-.27,f'64 次调用中 {states.sum()} 次返回候选\n求解器返回 ≠ 独立核验通过',ha='center',transform=cx.transAxes,fontsize=9.4)
    panel(cx,'(c)')
    fig.legend(handles=[Patch(fc=BLUE,label='求解器返回候选'),Patch(fc='#F1F3F4',ec=GRAY,label='未返回候选；不等于已证不可行')],loc='upper right',bbox_to_anchor=(.96,1),frameon=False,ncol=2)
    save(fig,'图2_自适应阈值空间与实际探索状态')
if __name__=='__main__':main()
