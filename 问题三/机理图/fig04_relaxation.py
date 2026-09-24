"""A fully specified toy MILP and finite-model constraint expansion, not physical hulls."""
from plot_style import *
def main():
    fig,(ax,bx)=plt.subplots(1,2,figsize=(11.8,5),gridspec_kw={'width_ratios':[1,1.35]})
    fig.subplots_adjust(left=.075,right=.98,bottom=.22,top=.82,wspace=.28)
    toy=DATA['toy'];poly=np.array(toy['vertices']);pts=np.array(toy['integers']);lp=toy['LP']
    ax.add_patch(Polygon(poly,fc=GRAY,ec=INK,alpha=.32,lw=1))
    ax.scatter(pts[:,0],pts[:,1],s=32,color=INK,zorder=3)
    xx=np.linspace(0,3.1,100)
    ax.plot(xx,toy['LB']-xx,color=ORANGE,ls='--',lw=1.2)
    ax.plot(xx,toy['UB']-xx,color=BLUE,ls=':',lw=1.3)
    ax.scatter(*lp,marker='D',s=65,color=ORANGE,zorder=5)
    ip=np.array(toy['IP']);ax.scatter(ip[:,0],ip[:,1],s=90,marker='x',color=BLUE,lw=2,zorder=5)
    ax.annotate(r'LP: $(4/3,4/3)$'+'\n'+r'$LB=8/3$',xy=lp,xytext=(.05,.18),fontsize=10,color=ORANGE,arrowprops=dict(arrowstyle='-',color=ORANGE))
    ax.text(.50,1.06,r'$\min\ u+v$',transform=ax.transAxes,ha='center',fontsize=12)
    ax.text(.05,.96,r'$2u+v\geq4,\ u+2v\geq4$'+'\n'+r'$0\leq u,v\leq3$',transform=ax.transAxes,va='top',fontsize=10)
    ax.set(xlim=(-.05,3.2),ylim=(-.05,3.3),xticks=[0,1,2,3],yticks=[0,1,2,3],xlabel=r'$u$',ylabel=r'$v$')
    panel(ax,'(a)');ax.text(.5,-.27,'可手算的合成例：整数最优值 = 3\n灰色松弛域不代表实际无人机解空间',transform=ax.transAxes,ha='center',fontsize=9.5)
    bx.set(xlim=(0,1),ylim=(0,1));bx.axis('off');panel(bx,'(b)')
    for rect,label,loc,color in [((.04,.09,.94,.84),r'$\mathcal{R}_0$：初始外松弛',(.075,.87),GRAY),
         ((.21,.19,.71,.56),r'$\mathcal{R}_q$：逐轮补充约束',(.25,.69),BLUE),
         ((.43,.26,.43,.27),r'$\mathcal{X}_{\mathrm{cert}}$：完整有限模型',(.455,.445),GREEN)]:
        x,y,w,h=rect;bx.add_patch(Rectangle((x,y),w,h,fc=color,ec=color,alpha=.12,lw=1.2))
        bx.text(*loc,label,fontsize=10,color=INK)
    bx.text(.47,.33,'资源无冲突 + 原子通信齐全',fontsize=9.4,color=GREEN)
    bx.text(.26,.59,'补：机体／电池先后；选中路线通信块',fontsize=9.2,color=BLUE)
    bx.text(.065,.02,r'$\mathcal{X}_{\mathrm{cert}}\subseteq\mathcal{R}_q\subseteq\mathcal{R}_0$',fontsize=12)
    bx.text(.5,-.15,'集合边界仅为机理示意；冻结 Ω、ε、目标与时域\n释放整数变量可再得 LP 下界；保守认证域不等于全物理域',transform=bx.transAxes,ha='center',fontsize=9.5)
    fig.legend(handles=[Patch(fc=GRAY,alpha=.32,label='合成 LP 可行域'),Line2D([],[],marker='o',color=INK,ls='',label='合成整数可行点'),
         Line2D([],[],marker='D',color=ORANGE,ls='',label='合成 LP 最优点'),Line2D([],[],marker='x',color=BLUE,ls='',label='合成整数最优点')],loc='upper center',bbox_to_anchor=(.5,1.005),ncol=4,frameon=False)
    save(fig,'图4_连续松弛与逐轮补约束的解空间')
if __name__=='__main__':main()
