
import argparse
import json
from pathlib import Path
import numpy as np
import pandas as pd
from pan import BASE as PAN

def verify(root):
    catalog=pd.read_json(root/"transport"/"datasets.json")
    actual={str(r['id']):r['metadata']['stats'] for _,entry in catalog.iterrows() for r in entry.resources if r.get('metadata',{}).get('stats')}
    archive_jobs=pd.read_json(root/'ci'/'artifacts.json')
    verified={};plans=0
    for source in ['transport','ci']:
        directory=root/source;m=pd.read_csv(directory/'manifest.tsv',sep='\t')
        projected=None
        if source=='ci':
            parts=[pd.read_csv(p,sep='\t') for p in (directory/'projected').glob('*.tsv.gz')]
            projected=pd.concat(parts,ignore_index=True).dropna(subset=['table','report_sha256']).set_index(['run','variant','feed','table'])
            assert len(archive_jobs)==40 and archive_jobs.run.nunique()==20
        totals=[0,0,0]
        for row in m[m.status.eq('ok')].itertuples():
            pref=Path(row.prefix)
            masks=np.fromfile(pref.with_suffix('.rows'),dtype='<u8')
            Q=pd.read_csv(pref.with_suffix('.tsv'),sep='\t',dtype={'must_null':'uint64','must_present':'uint64'})
            assert len(masks)==int(row.rows) and (Q.l==0).all() and (Q.r==len(masks)).all()
            ids=Q.request_id.drop_duplicates().to_list();distinct=Q.drop_duplicates(['l','r','must_null','must_present'])
            counts={}
            for x in distinct.itertuples():
                a,b=int(x.must_null),int(x.must_present)
                counts[a,b]=int(np.count_nonzero(((masks&a)==a)&((masks&b)==0)))
            if source=='transport':
                expected=[actual[str(row.resource)][k] for k in json.loads(row.labels)]
                assert ids==[1] and expected==json.loads(row.observed)
            else:
                prov=pd.read_csv(pref.with_suffix('.provenance.tsv'),sep='\t')
                assert ids==prov.request_id.tolist() and len(ids)==40
                assert prov.run.nunique()==20 and (prov.groupby('run').variant.nunique()==2).all()
                assert pd.to_datetime(prov.reported_at,utc=True).is_monotonic_increasing
                for r in prov.itertuples():
                    obs=projected.loc[(r.run,r.variant,row.feed,row.table)]
                    assert r.report_sha256==obs.report_sha256 and r.observed==obs.observed
                expected=json.loads(row.observed)
            calculated=[counts[int(a),int(b)] for a,b in zip(Q.must_null,Q.must_present)]
            assert calculated==expected*len(ids),(row.prefix,expected)
            totals[0]+=len(masks);totals[1]+=len(ids);totals[2]+=len(calculated);plans+=1
        verified[source]={'rows':totals[0],'scope_calls':totals[1],'values':totals[2]}
    print(json.dumps({'tables':plans,'verified':verified},indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=PAN.parent);verify(p.parse_args().root)
