
from pathlib import Path
import argparse, os, json, numpy as np, pandas as pd
P=Path(__file__).resolve().parents[2];D=P/'data'

rules={
'storm':[
('BEGIN_LAT BEGIN_LON END_LAT END_LON',''),('BEGIN_LAT BEGIN_LON','END_LAT'),('END_LAT END_LON','BEGIN_LAT'),('DAMAGE_PROPERTY DAMAGE_CROPS',''),('DAMAGE_PROPERTY','DAMAGE_CROPS'),('DAMAGE_CROPS','DAMAGE_PROPERTY'),('MAGNITUDE','MAGNITUDE_TYPE'),('TOR_LENGTH TOR_WIDTH','TOR_F_SCALE')],
'maude':[('DATE_OF_EVENT','DATE_REPORT'),('DATE_REPORT','DATE_OF_EVENT'),('DATE_RECEIVED DATE_REPORT DATE_OF_EVENT',''),('REPORT_TO_FDA','DATE_REPORT_TO_FDA'),('DATE_REPORT_TO_FDA','REPORT_TO_FDA'),('DATE_FACILITY_AWARE','DATE_REPORT_TO_MANUFACTURER'),('DATE_FACILITY_AWARE DATE_REPORT_TO_MANUFACTURER',''),('HEALTH_PROFESSIONAL','REPORTER_OCCUPATION_CODE')],
'survey':[('Currency','CompTotal'),('CompTotal','Currency'),('Currency CompTotal',''),('Employment','RemoteWork'),('LanguageHaveWorkedWith','LanguageWantToWorkWith'),('DatabaseHaveWorkedWith','DatabaseWantToWorkWith'),('PlatformHaveWorkedWith','PlatformWantToWorkWith'),('WebframeHaveWorkedWith','WebframeWantToWorkWith')],
'nhanes':[('MCQ010','MCQ025'),('MCQ010 MCQ025',''),('MCQ160A','MCD180A'),('MCQ160B','MCD180B'),('MCQ160C','MCD180C'),('MCQ160D','MCD180D'),('MCQ160E','MCD180E'),('MCQ160F','MCD180F')]}
def make_case(name):
    f=D/(name+'.npz');m=np.load(f);a=m['masks'];names=list(m['names']); n=len(a); pre=D/(name+'_case')
    if not pre.with_suffix('.rows').exists():os.link(f.with_suffix('.rows'),pre.with_suffix('.rows'))
    mask=lambda fields:sum(1<<names.index(col) for col in fields.split())
    res=[]
    with pre.with_suffix('.queries').open('w') as dst:
        for N in [1,24,384,1536]:
            rng=np.random.default_rng(904);zs=[]
            for i in range(N):
                width=max(1,int(n*[.001,.01,.1,.5][i%4]));l=int(rng.integers(n-width+1));zs.append((l,l+width))
            for j,(present,missing) in enumerate(rules[name]):
                x,y=mask(missing),mask(present)
                for l,r in zs:dst.write(f'{N}-named-0-{j} {x} {y} {l} {r}\n')
                if N==1:res.append((name,j,present,missing,int(np.count_nonzero(((a&x)==x)&((a&y)==0)))))
    return res
if __name__=='__main__':
    out=[]
    for name in rules:out+=make_case(name)
    pd.DataFrame(out,columns=['dataset','rule','present','missing','whole_table_count']).to_csv(P/'runs'/'case_manifest.tsv',sep='\t',index=False)
