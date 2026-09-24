from pathlib import Path
import json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Polygon,Rectangle,Patch,FancyArrowPatch,Ellipse
OUT=Path(__file__).resolve().parent
DATA=json.loads((OUT/'mechanism_data.json').read_text(encoding='utf-8'))
BLUE='#376B8E';ORANGE='#B65D31';GRAY='#BAC3C9';INK='#20262B';GREEN='#517A64';PURPLE='#786A91'
plt.rcParams.update({'font.family':['Noto Serif SC','Times New Roman'],'font.size':10.5,
 'axes.labelsize':10.5,'xtick.labelsize':9.5,'ytick.labelsize':9.5,'legend.fontsize':9,
 'mathtext.fontset':'stix','axes.unicode_minus':False,'axes.spines.top':False,
 'axes.spines.right':False,'axes.linewidth':.8,'figure.dpi':130,'savefig.dpi':300,
 'pdf.fonttype':42,'ps.fonttype':42,'svg.fonttype':'none','hatch.linewidth':.6})
def save(fig,name):
    for ext in ['png','pdf','svg']:fig.savefig(OUT/f'{name}.{ext}',bbox_inches='tight',pad_inches=.18)
    plt.close(fig)
def panel(ax,s):ax.text(-.12,1.05,s,transform=ax.transAxes,fontsize=14)
def arrow(ax,start,end,color=INK,**kw):
    ax.annotate('',xy=end,xytext=start,arrowprops=dict(arrowstyle='->',color=color,lw=1.2,**kw))
def objectives():return np.array([r['objective'] for r in DATA['archive']])
