
import argparse
import json
import os
import sys
import time
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(HERE.parent/'revision'))
os.environ.setdefault('SCOPECNT_EXTENSION',str(ROOT/'compiled'/'duckdb155_roaring'/'scopecount.duckdb_extension'))
import ci_replay
import replay
import seeded

METHODS=('tree_direct','bitmap_direct','roaring_direct')


def run_group(group,out,bts):
    base=ROOT/'traces'/'ci'
    if group=='domains':
        jobs=[]
        for name in seeded.SOURCES:
            prefix=ROOT/'data'/name
            jobs.append((name,prefix.with_suffix('.rows'),seeded.requests_for(prefix),None))
    elif group=='ci':
        _,selected=ci_replay.select(base)
        assert len(selected)==128
        jobs=[]
        for row in selected.itertuples():
            prefix=base/'feeds'/row.feed/row.table
            jobs.append((row.feed+'-'+row.table,prefix.with_suffix('.rows'),prefix.with_suffix('.tsv'),json.loads(row.observed)))
    else:
        jobs=[('BTS',bts/'bts.rows',bts/'bts.trace.tsv',None)]
    directory=out/group
    directory.mkdir(parents=True,exist_ok=True)
    con=replay.connect()
    try:
        for i,(name,rows,trace,expected) in enumerate(jobs,1):
            target=directory/(name+'.tsv')
            if target.exists():continue
            start=time.perf_counter()
            result=replay.run(rows,trace,5,METHODS,con,name,balanced=True)
            if expected is not None:
                for record in result:
                    if list(map(int,record['results'].split(',')))!=expected:
                        raise AssertionError('publisher output mismatch: '+name)
            replay.save(result,target)
            if group!='ci' or i%16==0:
                print(group,i,len(jobs),name,len(result),round(time.perf_counter()-start,2),'seconds',flush=True)
    finally:
        con.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--groups',nargs='+',default=('domains','ci','bts'),choices=['domains','ci','bts'])
    p.add_argument('--out',type=Path,default=ROOT/'revision'/'roaring')
    p.add_argument('--bts',type=Path,default=ROOT/'datasets/bts')
    a=p.parse_args()
    for group in a.groups:run_group(group,a.out,a.bts)
