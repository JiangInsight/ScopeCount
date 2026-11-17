from pathlib import Path
import numpy as np,pandas as pd, matplotlib.pyplot as plt
P=Path(__file__).resolve().parents[2]; O=Path(__file__).resolve().parents[1];R=P/'runs'
ds=['diabetes','nhanes','scania','storm','crash','survey','taxi','maude']
cold=[];even=[];row=[]
for d in ds:
    q=pd.read_csv(R/(d+'.joint.tsv'),sep='\t');q=q[q.width==8].copy();q['total']=q.exec_ns+q.compile_ns
    tm=q.groupby(['method','bundle']).total.median().groupby('method').sum()/1e6
    build=q.groupby('method').index_ns.first()/1e6
    t,b='frontier_joint','cached_bitmaps';cold.append((tm[t]+build[t])/(tm[b]+build[b]));even.append((build[t]-build[b])/(tm[b]-tm[t])*21 if tm[t]<tm[b] and build[t]>build[b] else np.nan)
    row.append([d,build[t],tm[t],build[b],tm[b],cold[-1],even[-1]])
f=pd.DataFrame(row,columns=['ds','treebuild_ms','treequery_ms','bitmapbuild_ms','bitmapquery_ms','cold_ratio','breakeven_bundles'])
f.to_csv(R/'investment.tsv',sep='\t',index=False)
fig,axs=plt.subplots(1,2,figsize=(6.7,2.25),layout='constrained',sharey=True);y=np.arange(len(ds))
for ax,plan in zip(axs,['tree','bitmap']):
    a=f[plan+'build_ms'];z=f[plan+'query_ms'];ax.barh(y,a,color='#466c81',label='Build index');ax.barh(y,z,left=a,color='#ccc',edgecolor='0.4',hatch='//',linewidth=.2,label='Run 21 bundles')
    ax.set_yticks(y,[d.upper() if d in ['maude','nhanes'] else d.title() for d in ds],fontsize=8);ax.set_xscale('log');ax.set_xlabel('Milliseconds (log scale)',fontsize=8);ax.tick_params(axis='x',labelsize=8);ax.set_title('Shared counter tree' if plan=='tree' else 'Prepared bitmaps',fontsize=9);ax.set_xlim(.15,1100);ax.invert_yaxis() if ax==axs[0] else None
axs[1].legend(fontsize=7,loc='upper right');fig.savefig(O/'figures'/'investment.pdf');plt.close(fig)
fig,ax=plt.subplots(figsize=(6.9,2),layout='constrained');ax.set_xlim(0,10);ax.set_ylim(0,4);ax.axis('off')
def box(x,y,s,fc='.95'):ax.text(x,y,s,ha='center',va='center',fontsize=8,bbox=dict(boxstyle='round,pad=.33',fc=fc,ec='.35',lw=.8))
def arr(x1,y1,x2,y2):ax.annotate('',(x2,y2),(x1,y1),arrowprops=dict(arrowstyle='->',color='.25',lw=.9))
box(1.25,2,'Source rows\nnull signatures');box(3.75,3,'Signature tree\nrow-position ranks');box(3.75,1,'Column bitmaps\nword-rank prefixes')
box(6.6,3,'Joint labeling\nsigned output masks');box(6.6,1,'Prepared rules\nbittests or intersections')
box(9.2,2,'One vector\nper slice')
for seg in [(2.14,2.22,2.85,2.9),(2.14,1.78,2.85,1.1),(4.84,3,5.65,3),(4.84,1,5.65,1),(7.68,2.9,8.6,2.2),(7.68,1.1,8.6,1.8)]:arr(*seg)
ax.text(6.6,2,'Placement chooses outputs',ha='center',va='center',fontsize=8,fontstyle='italic')
fig.savefig(O/'figures'/'physical.pdf');plt.close(fig)
print(f.to_string(index=False))
