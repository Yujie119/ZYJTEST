"""Actual pilot epsilon rules, threshold geometry, outcomes and duplicate stop."""
from plot_style import *
from mpl_toolkits.mplot3d.art3d import Poly3DCollection

def main():
    h=DATA['historical_epsilon'];F=np.array(h['initial_objectives']);mi=np.array(h['minimum']);ma=np.array(h['maximum'])
    fig=plt.figure(figsize=(12.5,4.5));gs=fig.add_gridspec(1,3,width_ratios=[1.03,1.02,1.12],left=.045,right=.99,bottom=.17,top=.84,wspace=.25)
    ax=fig.add_subplot(gs[0],projection='3d');bx=fig.add_subplot(gs[1]);cx=fig.add_subplot(gs[2]);cx.axis('off');cx.set(xlim=(0,1),ylim=(0,1))
    # N/E use pilot min-max; L uses physical zero to pilot maximum.
    Z=np.c_[(F[:,0]-mi[0])/(ma[0]-mi[0]),(F[:,1]-mi[1])/(ma[1]-mi[1]),F[:,3]/ma[3]]
    ax.scatter(Z[:,0],Z[:,1],Z[:,2],s=28,color=INK,depthshade=False)
    for dim in range(3):
        others=[v for v in range(3) if v!=dim]
        for p in [0,1]:
            for q in [0,1]:
                start=np.zeros(3);stop=np.zeros(3);stop[dim]=1
                start[others]=[p,q];stop[others]=[p,q]
                ax.plot(*np.vstack([start,stop]).T,color='#94A8B6',lw=.65)
    lmid=(mi[3]+ma[3])/2/ma[3]
    planes=[([[0,.5,0],[1,.5,0],[1,.5,1],[0,.5,1]],ORANGE),
        ([[0,0,lmid],[1,0,lmid],[1,1,lmid],[0,1,lmid]],BLUE),
        ([[0,0,0],[1,0,0],[1,1,0],[0,1,0]],GREEN)]
    for verts,color in planes:ax.add_collection3d(Poly3DCollection([verts],facecolors=color,edgecolors=color,alpha=.13,lw=.8))
    ax.set(xlim=(-.1,1.08),ylim=(-.05,1.05),zlim=(-.05,1.05),xlabel=r'$\widetilde N$',ylabel=r'$\widetilde E$',zlabel='',xticks=[0,1],yticks=[0,.5,1],zticks=[0,1])
    ax.text2D(.84,.95,r'$L/L_{\max}^{\mathcal{A}}$',transform=ax.transAxes,fontsize=10)
    ax.view_init(elev=21,azim=-56);ax.set_box_aspect((1,1,.9));ax.grid(False)
    for axis in [ax.xaxis,ax.yaxis,ax.zaxis]:axis.pane.set_alpha(0)
    ax.text2D(-.07,1.04,'(a)',transform=ax.transAxes,fontweight='bold',fontsize=13)
    ax.text2D(.03,-.21,'6 个已知方案的阈值坐标\n'+r'$C_{\max}$ 在子问题中最小化',transform=ax.transAxes,fontsize=10)
    Emid=h['records'][1]['cap']['E'];Lmid=h['records'][2]['cap']['L']
    bx.scatter(F[:,1],F[:,3],s=38,c=INK,zorder=5)
    bx.axvline(Emid,color=ORANGE,ls=(0,(4,3)),lw=1.25)
    bx.axhline(Lmid,color=BLUE,ls=(0,(4,3)),lw=1.25)
    bx.axhline(0,color=GREEN,lw=1.5)
    bx.annotate(r'$\varepsilon_E=(E_{\min}^{\mathcal{A}}+E_{\max}^{\mathcal{A}})/2$',xy=(Emid,430),xytext=(61,605),fontsize=9.4,color=ORANGE,
        arrowprops=dict(arrowstyle='-',color=ORANGE,lw=.75))
    bx.text(89,Lmid+20,rf'$\varepsilon_L={Lmid:.3f}$ s',ha='right',color=BLUE,fontsize=9)
    bx.text(89,23,r'$\varepsilon_L=0$',ha='right',color=GREEN,fontsize=10)
    bx.annotate('能耗阈值返回',xy=(F[0,1],F[0,3]),xytext=(61,550),fontsize=8.8,color=ORANGE)
    bx.annotate('迟到阈值返回',xy=(F[1,1],F[1,3]),xytext=(61,145),fontsize=8.8,color=BLUE,
        arrowprops=dict(arrowstyle='-',color=BLUE,lw=.75))
    bx.set(xlim=(58,91),ylim=(-45,645),xlabel='总能耗 $E$ (kWh)',ylabel='加权迟到 $L$ (s)');panel(bx,'(b)')
    panel(cx,'(c)')
    rows=[('架次收紧',r'$\varepsilon_N=20-1=19$','旧库内不可行',ORANGE),
        ('能耗中点',rf'$\varepsilon_E={Emid:.3f}$','限时有解；未获最优认证',ORANGE),
        ('迟到中点',rf'$\varepsilon_L={Lmid:.3f}$','限时有解；未获最优认证',BLUE),
        ('零迟到',r'$\varepsilon_L=0$','限时无解；不能判不可行',GREEN)]
    for y,(title,formula,status,color) in zip([.95,.72,.49,.26],rows):
        cx.text(0,y,title,fontsize=10.5,color=color,va='top')
        cx.text(.40,y,formula,fontsize=10,va='top')
        cx.text(.02,y-.105,status,fontsize=9.2,color=INK,va='top')
        cx.plot([0,.98],[y-.17,y-.17],transform=cx.transAxes,color='#DDE2E5',lw=.7)
    cx.text(0,-.095,'第二轮：阈值重复 → 0 个新任务\n范围未变不等于完整搜索已结束',fontsize=10,linespacing=1.55,va='top')
    fig.text(.51,.98,'历史 558 条工作库的真实预实验；中点随当前档案更新，重复阈值跳过',ha='center',va='top',fontsize=10,color='#606C74')
    save(fig,'图2_自适应epsilon阈值与真实求解状态')

if __name__=='__main__':main()
