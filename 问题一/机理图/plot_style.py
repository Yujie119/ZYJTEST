from pathlib import Path
import json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Polygon, Rectangle

OUT=Path(__file__).resolve().parent
DATA=json.loads((OUT/'mechanism_data.json').read_text(encoding='utf-8'))
BLUE='#376B8E'
ORANGE='#B65D31'
GRAY='#B9C1C7'
INK='#20262B'
plt.rcParams.update({
    'font.family':['Noto Serif SC','Times New Roman'], 'font.size':11,
    'axes.labelsize':11,'xtick.labelsize':10,'ytick.labelsize':10,
    'legend.fontsize':9,'mathtext.fontset':'stix','axes.unicode_minus':False,
    'axes.spines.top':False,'axes.spines.right':False,
    'axes.linewidth':.8,'lines.linewidth':1.25,
    'figure.dpi':130,'savefig.dpi':320,'pdf.fonttype':42,'ps.fonttype':42,
    'svg.fonttype':'none','hatch.linewidth':.55})

def save(fig,name):
    for ext in ('png','pdf','svg'):
        fig.savefig(OUT/f'{name}.{ext}',bbox_inches='tight',pad_inches=.13)
    plt.close(fig)

def panel(ax,label):
    ax.text(-.10,1.04,label,transform=ax.transAxes,fontweight='bold',fontsize=13)

def front():
    return np.array([[p['N'],p['E_kWh'],p['T_s']] for p in DATA['pareto']])

def outline(ax,verts,**kwargs):
    verts=np.asarray(verts)
    return ax.plot(*np.vstack([verts,verts[0]]).T,**kwargs)
