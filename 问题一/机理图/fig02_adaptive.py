"""Actual regions 3 -> 4 -> 5; not a fictitious recursive 3D box algorithm."""
from plot_style import *
from mpl_toolkits.mplot3d.art3d import Poly3DCollection
import itertools

def cube(ax):
    vertices=np.array(list(itertools.product([0,1],repeat=3)))
    for i,v in enumerate(vertices):
        for u in vertices[i+1:]:
            if np.sum(v!=u)==1:
                ax.plot(*np.array([v,u]).T,color='#758A99',lw=.75,alpha=.8)
    faces=[[[0,0,0],[1,0,0],[1,1,0],[0,1,0]],
           [[0,1,0],[1,1,0],[1,1,1],[0,1,1]],
           [[0,0,1],[1,0,1],[1,1,1],[0,1,1]]]
    ax.add_collection3d(Poly3DCollection(faces,facecolors=BLUE,alpha=.07,edgecolors='none'))
    ax.set(xlim=(-.13,1.18),ylim=(-.13,1.18),zlim=(-.13,1.18),
           xlabel=r'$\widetilde E$',ylabel=r'$\widetilde N$',zlabel='')
    ax.text2D(.99,.58,r'$\widetilde T$',transform=ax.transAxes,ha='center',fontsize=12)
    for axis in (ax.xaxis,ax.yaxis,ax.zaxis):
        axis.set_ticks([0,1]);axis.pane.fill=False;axis.pane.set_edgecolor('white')
    ax.grid(False);ax.view_init(elev=23,azim=-56);ax.set_proj_type('ortho')
    ax.set_box_aspect((1,1,1))
    ax.tick_params(pad=-1)
    ax.xaxis.labelpad=-3;ax.yaxis.labelpad=-3;ax.zaxis.labelpad=-3

def main():
    A,B=front();F=front(); lo=F.min(axis=0);span=F.max(axis=0)-lo
    norm=(F-lo)/span
    a,b=norm[:,[1,0,2]]
    fig=plt.figure(figsize=(11.8,4.0))
    gs=fig.add_gridspec(1,3,wspace=.15,left=.025,right=.965,bottom=.19,top=.83)
    ax=fig.add_subplot(gs[0],projection='3d');bx=fig.add_subplot(gs[1]);cx=fig.add_subplot(gs[2],projection='3d')
    for aa in (ax,cx):cube(aa)
    ax.scatter(*a,s=48,facecolors='white',edgecolors=BLUE,depthshade=False)
    ax.text(*a,'  $A$',color=BLUE)
    ax.scatter(*b,s=60,marker='x',color=ORANGE,depthshade=False,lw=1.8)
    ax.text(b[0],b[1],b[2]+.07,'$B$',color=ORANGE)
    ax.text2D(.03,1.08,'(a)',transform=ax.transAxes,fontweight='bold',fontsize=13)
    ax.text2D(.5,-.17,'区域 3：返回 $B$\n'+r'$\varepsilon_N=19,\ \varepsilon_T=+\infty$',transform=ax.transAxes,ha='center',fontsize=10)
    bx.add_patch(Rectangle((0,0),1,1,facecolor=BLUE,alpha=.12,edgecolor='#758A99',lw=.8))
    bx.axhline(1,color=ORANGE,ls=(0,(4,3)),lw=1)
    bx.scatter([0],[1],s=58,facecolor='white',edgecolor=ORANGE,lw=1.5,zorder=4)
    bx.scatter([1],[0],s=70,marker='x',color=BLUE,lw=1.8,zorder=4)
    bx.annotate('$B$：排除',(0,1),xytext=(.20,1.12),color=ORANGE)
    bx.annotate('$A$：返回',(1,0),xytext=(.48,.10),color=BLUE)
    bx.annotate('',xy=(.55,.32),xytext=(.55,.84),arrowprops={'arrowstyle':'->','color':BLUE,'lw':1.4})
    bx.text(.51,.60,r'$\varepsilon_T\downarrow$',ha='right',color=BLUE)
    bx.text(.50,.91,r'$T_B-0.001\ \mathrm{s}$',ha='center',fontsize=10,color=ORANGE)
    bx.set(xlim=(-.15,1.2),ylim=(-.18,1.3),xticks=[0,1],yticks=[0,1],xlabel=r'$\widetilde E$',ylabel=r'$\widetilde T$')
    bx.set_aspect('equal',adjustable='box');panel(bx,'(b)')
    bx.text(.5,-.29,'区域 4：投影与收紧\n'+r'$\varepsilon_N=19,\ \varepsilon_T=T_B-0.001$ s',transform=bx.transAxes,ha='center',fontsize=10)
    cx.scatter(*b,s=48,facecolors='white',edgecolors=ORANGE,depthshade=False)
    cx.text(b[0],b[1],b[2]+.06,'$B$',color=ORANGE)
    cx.scatter(*a,s=52,facecolors='white',edgecolors='#65737E',depthshade=False,lw=1.3)
    cx.text(a[0]-.34,a[1],a[2]+.16,'$A$：已排除',color='#65737E',fontsize=10)
    cx.add_collection3d(Poly3DCollection([[[0,0,0],[1,0,0],[1,1,0],[0,1,0]]],
        facecolors=BLUE,alpha=.18,edgecolors=BLUE,linestyles='--',linewidths=1))
    cx.text2D(.5,.93,r'$\varepsilon_T<T_A\ \Rightarrow\ \varnothing$',transform=cx.transAxes,ha='center',color=BLUE,fontsize=12)
    cx.text2D(.03,1.08,'(c)',transform=cx.transAxes,fontweight='bold',fontsize=13)
    cx.text2D(.5,-.17,'区域 5：整数不可行，本分支终止\n'+r'$\varepsilon_N=19,\ \varepsilon_T=T_A-0.001$ s',transform=cx.transAxes,ha='center',fontsize=10)
    fig.text(.5,.985,'三维盒表示理想点—最差非支配点显示窗口；盒内连续位置不代表可行方案',ha='center',fontsize=10,color='#4D5961')
    save(fig,'图2_三目标自适应epsilon搜索')

if __name__=='__main__': main()
