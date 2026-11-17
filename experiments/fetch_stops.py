import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pyreadr
import requests

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'research/artifact/livegroups'))
import stops

FIELDS=['date','subject_race','outcome','location','time','subject_sex','citation_issued','subject_age','lat','lng','warning_issued','arrest_made','search_conducted','violation','officer_id_hash','contraband_found','search_basis','reason_for_stop','county_name','vehicle_make']


def prepare(name,cache):
    if name not in stops.WEEKLY:raise ValueError('Unknown source: '+name)
    url,filename=stops.source(name)
    cache.mkdir(parents=True,exist_ok=True)
    raw=cache/filename
    if not raw.exists():
        partial=raw.with_suffix('.partial')
        with requests.get(url,stream=True,timeout=(30,300)) as response:
            response.raise_for_status()
            with partial.open('wb') as out:
                for block in response.iter_content(1<<20):out.write(block)
        partial.replace(raw)
    expected={x['dataset']:x for x in json.loads((ROOT/'research/artifact/livegroups/results/source_manifest.json').read_text())}[name]
    digest=stops.sha(raw)
    if digest!=expected['source_sha256']:raise ValueError('Pinned source checksum mismatch')
    data=pyreadr.read_r(str(raw))[None]
    fields=[f for f in FIELDS if f in data]
    selected=data.loc[data['type'].astype(str)=='vehicular']
    n=len(selected)
    valid=selected[fields].notna()
    masks=np.zeros(n,dtype=np.int32)
    for i,f in enumerate(fields):masks|=(~valid[f].to_numpy()).astype(np.int32)<<i
    dates=pd.to_datetime(selected['date'],errors='raise')
    days=(dates-pd.Timestamp('1970-01-01')).dt.days
    week=np.where(dates.notna(),np.floor((days+3)/7),stops.MISSING).astype(np.int32)
    hour=np.full(n,stops.MISSING,dtype=np.int32)
    if 'time' in fields:
        values=selected['time']
        def hours(v):
            if pd.isna(v):return stops.MISSING
            if hasattr(v,'hour'):return v.hour
            if isinstance(v,(int,float,np.number)):return int(v//3600)
            return int(pd.to_timedelta(str(v)).total_seconds()//3600)
        hour=values.map(hours).to_numpy(dtype=np.int32)
        if np.any((hour!=stops.MISSING)&((hour<0)|(hour>=24))):raise ValueError('Invalid hourly key')
    out=cache/'panels'/name
    out.mkdir(parents=True,exist_ok=True)
    for label,array in [('masks',masks),('week',week),('hour',hour)]:array.astype('<i4').tofile(out/(label+'.i32'))
    (out/'fields.txt').write_text('\n'.join(fields)+'\n')
    (out/'sizes.txt').write_text(f'{len(data)} {n}\n')
    dims=['week']+(['hour'] if name in stops.HOURLY else [])
    oracle={}
    for dim in dims:
        keys=week if dim=='week' else hour
        counted=[f for f in fields if f!=('date' if dim=='week' else 'time')]
        values=(~selected[counted].notna()).sum(axis=1).to_numpy(dtype=np.int64)
        grouped=pd.DataFrame({'key':keys,'missing':values})
        grouped=grouped[grouped.key!=stops.MISSING].groupby('key').missing.agg(['size','sum'])
        file=out/f'oracle-{dim}.csv'
        with file.open('w',newline='') as f:
            writer=csv.writer(f,quoting=csv.QUOTE_NONNUMERIC,lineterminator='\n')
            writer.writerow(['key','n','missing'])
            writer.writerows((int(k),int(row['size']),int(row['sum'])) for k,row in grouped.iterrows())
        oracle[dim]=stops.oracle_sha(file)
    if oracle!=expected['oracle']:raise ValueError('Reconstructed answer differs from the independent frozen R oracle')
    columns={'week':pa.array(week.astype('uint32'),mask=week==stops.MISSING),'hour':pa.array(hour.astype('uint32'),mask=hour==stops.MISSING)}
    for f in fields:columns['v_'+f]=pa.array(np.ones(n,dtype=bool),mask=~valid[f].to_numpy())
    projected=out/'input.parquet'
    pq.write_table(pa.table(columns),projected,compression='zstd',row_group_size=122880)
    case=dict(dataset=name,release=filename,source=url,source_sha256=digest,raw_rows=len(data),vehicular_rows=n,fields=fields,queries=dims,projected_sha256=stops.sha(projected),oracle=oracle,program='https://github.com/saatvikkher/missing-traffic/blob/'+stops.EDITION)
    (out/'case.json').write_text(json.dumps(case,indent=2)+'\n')
    print(name,n,'rows;',len(grouped),'groups; source and independent R oracle hashes matched',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--cache',type=Path,required=True)
    parser.add_argument('--all',action='store_true')
    parser.add_argument('names',nargs='*',default=['ca_bakersfield'])
    args=parser.parse_args()
    for name in stops.WEEKLY if args.all else args.names:prepare(name,args.cache)
