"""Certified 2D projections of actual S003 integer / LP feasible sets."""
from plot_style import *

def sets(ax,lp,ip,points):
    ax.add_patch(Polygon(lp,closed=True,facecolor=GRAY,edgecolor=INK,lw=1.4,alpha=.7))
    ax.add_patch(Polygon(ip,closed=True,facecolor='white',edgecolor=INK,lw=1.0,hatch='////',alpha=.8))
    outline(ax,lp,color=INK,lw=1.5)
    outline(ax,ip,color=INK,lw=1.15,ls=(0,(3,2)))
    ax.scatter(*points.T,s=20,facecolor='white',edgecolor=INK,marker='s',lw=.7,zorder=4)

def main():
    r=DATA['relaxation']
    fig,(ax,bx)=plt.subplots(1,2,figsize=(10.3,4.2))
    fig.subplots_adjust(left=.075,right=.98,bottom=.16,top=.81,wspace=.28)
    sets(ax,np.array(r['decision_LP']),np.array(r['decision_IP_hull']),np.array(r['decision_points']))
    lp=np.array(r['LP_min_E_decision']);ip=np.array(r['IP_min_E_decision'])
    ax.scatter(*lp,s=68,marker='D',color=ORANGE,zorder=6)
    ax.scatter(*ip,s=68,marker='x',color=BLUE,lw=1.8,zorder=6)
    ax.annotate('LP 能耗最优\n'+r'$(0,\ 11/9)$',lp,xytext=(1.05,1.47),color=ORANGE,fontsize=10,
        bbox={'facecolor':'white','edgecolor':'none','alpha':.90,'pad':2},
        arrowprops={'arrowstyle':'-','color':ORANGE,'lw':.9})
    ax.annotate('整数能耗最优',ip,xytext=(1.9,.68),color=BLUE,fontsize=10,
        bbox={'facecolor':'white','edgecolor':'none','alpha':.90,'pad':2},
        arrowprops={'arrowstyle':'-','color':BLUE,'lw':.9})
    ax.set(xlim=(-.4,8.5),ylim=(-.17,2.95),xticks=range(0,9,2),yticks=[0,1,2],
        xlabel='S003 的 B 型架次 $n_B$',ylabel='S003 的 C 型架次 $n_C$')
    panel(ax,'(a)')
    transform=np.array([1,1/1000])
    sets(bx,np.array(r['objective_LP'])*transform,np.array(r['objective_IP_hull'])*transform,
        np.array(r['objective_points'])*transform)
    fl=np.array(r['LP_min_E_f'])[[1,2]]*transform
    fi=np.array(r['IP_min_E_f'])[[1,2]]*transform
    bx.scatter(*fl,s=68,marker='D',color=ORANGE,zorder=6)
    bx.scatter(*fi,s=68,marker='x',color=BLUE,lw=1.8,zorder=6)
    bx.annotate(f'LP: {fl[0]:.4f} kWh',fl,xytext=(fl[0]+3,fl[1]-.45),color=ORANGE,fontsize=10,
        arrowprops={'arrowstyle':'-','color':ORANGE,'lw':.9})
    bx.annotate(f'IP: {fi[0]:.4f} kWh',fi,xytext=(fi[0]+3.5,fi[1]+.1),color=BLUE,fontsize=10,
        arrowprops={'arrowstyle':'-','color':BLUE,'lw':.9})
    bx.set(xlabel='S003 能耗 $E_{003}$ (kWh)',ylabel='S003 作业时间 $T_{003}$ ($10^3$ s)')
    bx.margins(x=.07,y=.10)
    bx.text(.04,.96,f'枚举 {r["solutions"]} 个整数组批方案',transform=bx.transAxes,va='top',fontsize=10)
    panel(bx,'(b)')
    handles=[Rectangle((0,0),1,1,fc=GRAY,ec=INK,label='LP 松弛可行域的投影'),
        Rectangle((0,0),1,1,fc='white',ec=INK,hatch='////',label='整数凸包的投影'),
        Line2D([],[],marker='s',ls='',mfc='white',mec=INK,label='整数可行解的投影'),
        Line2D([],[],marker='D',ls='',color=ORANGE,label='LP 能耗最优'),
        Line2D([],[],marker='x',ls='',color=BLUE,label='整数能耗最优')]
    fig.legend(handles=handles,loc='upper center',bbox_to_anchor=(.5,1.015),ncol=3,frameon=False,columnspacing=1.5)
    save(fig,'图3_连续松弛与整数凸包')

if __name__=='__main__':main()
