
from pathlib import Path
import json,sys,math
import numpy as np,pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
P=Path(__file__).resolve().parents[2]; O=Path(__file__).resolve().parents[1];D=P/'data';R=P/'runs';F=O/'figures';F.mkdir(exist_ok=True)
DS=['diabetes','nhanes','scania','storm','crash','survey','taxi','maude']
N={'diabetes':'Diabetes','nhanes':'NHANES','scania':'Scania','storm':'Storm','crash':'Crash','survey':'Survey','taxi':'Taxi','maude':'MAUDE'}
def tsv(name):return pd.read_csv(R/name,sep='\t')
def put(fn,txt):(O/fn).write_text(txt+'\n',encoding='utf8')
def fmt(v):
    if v==0:return '0'
    if abs(v)<.01:return f'{v:.3f}'
    if abs(v)<10:return f'{v:.2f}'
    if abs(v)<100:return f'{v:.1f}'
    return f'{v:,.0f}'
def tab(fn,rows):put(fn,'\n'.join(' & '.join(map(str,r))+r' \\' for r in rows)+chr(10)+chr(92)+'bottomrule')
def loadb(d,suffix='joint',n=21):
    f=tsv(f'{d}.{suffix}.tsv'); assert len(f)==n*3*13*3,(d,len(f))
    assert not f[['bundle','width','method','rep']].duplicated().any()
    assert f.groupby(['bundle','width']).digest.nunique().max()==1
    f['total']=f.compile_ns+f.exec_ns
    v=f.groupby(['bundle','width','method']).median(numeric_only=True).reset_index();v['dataset']=d
    return v
b=pd.concat([loadb(d) for d in DS]);b8=b[b.width==8]
def grid(b,val):return b.groupby(['dataset','method'])[val].sum().unstack()
g=grid(b8,'total');ex=grid(b8,'exec_ns');co=grid(b8,'compile_ns');rr=grid(b8,'ranks');uu=grid(b8,'updates')
T=[];single=[];idxs=[];sqls=[];seeds=[];tail=[];rule_stats=[]
for d in DS:
    f=tsv(d+'.single.tsv');assert len(f)==168*13*3 and not f[['query','method','repeat']].duplicated().any()
    assert f.groupby('query').checksum.nunique().max()==1 and f.groupby('query').matched_sum.nunique().max()==1
    f['total']=f.compile_ns+f.exec_ns
    s=f.groupby(['query','method']).median(numeric_only=True).groupby('method').sum()
    single.append([N[d]]+[fmt(s.loc[m,'total']/168/1000) for m in ['scan','bitmap','block_hist','wavelet','global_hybrid','signed_hybrid','predicate_prefix']])
    ix=tsv(d+'.single.tsv.index.tsv').set_index('method')
    j=b8[b8.dataset==d].groupby('method').first()
    idxs.append([N[d]]+[fmt(j.loc[m,'index_bytes']/2**20) for m in ['frontier_joint','cached_bitmaps']]+[fmt(j.loc[m,'index_ns']/1e6) for m in ['frontier_joint','cached_bitmaps']]+[fmt((ix.loc[m,'payload_bytes']+ix.loc[m,'metadata_bytes'])/2**20) for m in ['wavelet','block_hist']])
    sql=tsv(d+'.sql.tsv');assert len(sql)==63 and not sql[['bundle','rep']].duplicated().any()
    sql['total']=sql.prepare_ns+sql.exec_ns
    sqls.append([d,float(sql.groupby('bundle').total.median().sum()/21/1000)])
    T.append([N[d]]+[fmt(g.at[d,m]/21000) for m in ['frontier_scalar','frontier_joint','fitch_near','leaf_union','cached_bitmaps','portfolio']]+[fmt(sqls[-1][1])])
    sf=b8[(b8.dataset==d)&(b8.method.isin(['frontier_joint','frontier_scalar','portfolio','cached_bitmaps']))].copy();sf['seed']=sf.bundle.str.split('-').str[0];v=sf.groupby(['seed','method']).total.sum().unstack();rat=v.frontier_scalar/v.frontier_joint
    tail.append([N[d],fmt(rat.min()),fmt(rat.max()),fmt(sf[sf.method=='frontier_joint'].total.quantile(.95)/1000),fmt(sf[sf.method=='cached_bitmaps'].total.quantile(.95)/1000),fmt((1-rr.at[d,'frontier_joint']/rr.at[d,'frontier_scalar'])*100)])
    meta=json.loads((D/(d+'.meta.json')).read_text());q=meta['queries'];sig=np.unique(np.load(D/(d+'.npz'))['masks']);r=[]
    for h in range(0,len(q),8):
        distinct=set()
        for v0 in q[h:h+8]:
            one,zero=int(v0['required_null']),int(v0['required_present']); y=((sig&one)==one)&((sig&zero)==0)
            if y.any() and not y.all():distinct.add(np.packbits(y).tobytes())
        r.append(len(distinct))
    rule_stats.append([d,r])
tab('tab_bundle.tex',T);tab('tab_scalar.tex',single);tab('tab_storage.tex',idxs);tab('tab_tail.tex',tail)
cases=pd.concat([loadb(d+'_case',n=4) for d in ['nhanes','storm','survey','maude']])
caseout=[]
for d in ['nhanes','storm','survey','maude']:
    sub=cases[(cases.dataset==d+'_case')&(cases.width==8)]
    vg=sub.pivot(index='ranges',columns='method',values='total')
    caseout.append([N[d]]+[fmt(vg.at[h,'cached_bitmaps']/vg.at[h,'frontier_joint']) for h in [1,24,384,1536]])
tab('tab_reuse.tex',caseout)
mid=b8[b8.method=='portfolio']; mixed=int(((mid.keep!=0)&(mid.keep!=255)).sum())
abrows=[]
for w in [2,4,8]:
    sl=b[b.width==w];rx=grid(sl,'ranks');up=grid(sl,'updates')
    for m in ['frontier_scalar','frontier_joint','joint4','joint16']:
        abrows.append([w,{'frontier_scalar':'Scalar','frontier_joint':'Min-read','joint4':'Weighted 4','joint16':'Weighted 16'}[m],f'{int(rx[m].sum()):,}',f'{int(up[m].sum()):,}',fmt((4*rx[m]+up[m]).sum()/(4*rx.frontier_scalar+up.frontier_scalar).sum())])
tab('tab_ablate.tex',abrows)
vlist=[]
for d in DS:
    q=b8[(b8.dataset==d)].pivot(index='bundle',columns='method',values='ranks')
    regs=rule_stats[DS.index(d)][1]
    good=[name for name,k in zip([v['id'] for v in json.loads((D/(d+'.meta.json')).read_text())['queries'][::8]],regs) if k==8]
    for nm in good:vlist.append((int(q.at[nm,'frontier_scalar']),int(q.at[nm,'frontier_joint'])))
cal=loadb('years','ext',1);scale=[]
for n in [50000,200000,800000,3216357]:
    vs=loadb('scale'+str(n),'ext',1).query('width==8').set_index('method')
    scale.append([f'{n:,}',f'{(int(vs.iloc[0].nodes)+1)//2:,}',fmt(vs.at['frontier_joint','index_ns']/1e6)]+[fmt(vs.at[m,'total']/1000) for m in ['frontier_joint','cached_bitmaps','portfolio']])
tab('tab_scale.tex',scale)


macs={}
def m(n,v):macs[n]=str(v)
frac=100*(1-rr.frontier_joint/rr.frontier_scalar)
m('RankLo',f'{frac.min():.1f}');m('RankHi',f'{frac.max():.1f}')
m('RangeLo',N[frac.idxmin()]);m('RangeHi',N[frac.idxmax()])
rat=g.frontier_scalar/g.frontier_joint;m('FastLo',fmt(rat.min()));m('FastHi',fmt(rat.max()));m('JointWins',int((rat>1).sum()))
m('CacheWins',int((g.cached_bitmaps<g.frontier_joint).sum()));m('Mixed',mixed)
m('DistinctBundles',len(vlist));m('DistinctCut',fmt((1-sum(y for _,y in vlist)/sum(x for x,_ in vlist))*100))
m('NoaaAnnual',fmt(cal.query("width==8 and method=='frontier_joint'").total.iloc[0]/1000))
m('NoaaSql',fmt(dict(sqls)['storm']));m('NoaaTree',fmt(g.at['storm','frontier_joint']/21000))
m('SurveyCached',fmt(g.at['survey','frontier_joint']/g.at['survey','cached_bitmaps']))
m('SharedWins',int((rr.frontier_joint < rr.frontier_scalar).sum()))
m('PureMixWins',int((g.portfolio<g.all_or_none).sum()))
m('PureCachedWins',int((g.portfolio<g.cached_bitmaps).sum()))
m('SurveyPrepare',fmt(co.at['survey','frontier_joint']/21000));m('SurveyRun',fmt(ex.at['survey','frontier_joint']/21000))
put('numbers.tex','\n'.join('\\newcommand{\\'+k+'}{'+v+'}' for k,v in macs.items()))

labels=['Scalar\nunion','Joint\nwhole tree','Joint\nfrontier','Leaf\nunion','Prepared\nbitmap','Mixed\nplacement']
ms=['frontier_scalar','fitch_near','frontier_joint','leaf_union','cached_bitmaps','portfolio']
fig,ax=plt.subplots(figsize=(6.8,2.85),layout='constrained');A=np.log2(g.loc[DS,ms].div(g.loc[DS,'frontier_joint'],axis=0).values);im=ax.imshow(A,cmap='RdBu_r',vmin=-5,vmax=5,aspect='auto')
for i in range(len(DS)):
    for j in range(len(ms)):
        val=2**A[i,j];ax.text(j,i,fmt(val),ha='center',va='center',fontsize=8,color='white' if abs(A[i,j])>2.7 else 'black')
ax.set_xticks(range(len(ms)),labels,fontsize=8);ax.set_yticks(range(len(DS)),[N[d] for d in DS],fontsize=8);ax.tick_params(length=0);fig.savefig(F/'regimes.pdf');plt.close(fig)
fig,ax=plt.subplots(figsize=(3.5,1.65),layout='constrained')
pos={'r':(.52,.96),'a':(.28,.68),'b':(.78,.68),'d':(.40,.40),'4':(.1,.09),'2':(.29,.09),'6':(.50,.09),'3':(.69,.09),'7':(.89,.09)}
for x,y in [('r','a'),('r','b'),('a','4'),('a','d'),('d','2'),('d','6'),('b','3'),('b','7')]:ax.plot([pos[x][0],pos[y][0]],[pos[x][1],pos[y][1]],color='.4',lw=1,zorder=0)
for key,(x,y) in pos.items():
    if key.isdigit():
        label={'4':'4: 00','2':'2: 10','6':'6: 01','3':'3: 10','7':'7: 01'}[key]
        ax.text(x,y,label,ha='center',va='center',fontsize=9,bbox=dict(boxstyle='round,pad=.20',fc='white',ec='black'))
    else:ax.scatter(x,y,s=34,c='.2',zorder=1)
ax.set(xlim=(0,1),ylim=(-.08,1.06));ax.axis('off');fig.savefig(F/'example.pdf');plt.close(fig)
print(json.dumps(macs,indent=2))
