



import argparse
import collections
import concurrent.futures
import hashlib
import json
import os
import zipfile
from pathlib import Path
import pandas as pd
try:
    import orjson
    loads=orjson.loads
except ImportError:
    loads=json.loads
from ci_download import BASE
from ci_inputs import RULES

def extract_job(job):
    rid=job["id"];out=[]
    with zipfile.ZipFile(BASE/f"{rid}.meta.zip") as mf:
        meta=loads(mf.read("gtfs_latest_versions.json"))
    with zipfile.ZipFile(BASE/f"{rid}.zip") as z:
        members=set(z.namelist())
        for feed,url in meta.items():
            if url!=f"https://files.mobilitydatabase.org/{feed}/latest.zip":continue
            for variant in ["reference","latest"]:
                f=f"{feed}/{variant}.json";info={"run":rid,"feed":feed,"variant":variant,"member":f}
                try:
                    if f not in members:raise ValueError("report absent")
                    raw=z.read(f)
                    d=loads(raw);s=d["summary"]
                    source=s["gtfsInput"]
                    if not (source==url or (source.startswith("file:///") and source.endswith(f"/feeds/{feed}/gtfs.zip"))):
                        raise ValueError("unknown input locator")
                    error=loads(z.read(f"{feed}/{variant}_errors.json"))
                    if any(int(v.get("totalNotices",1)) for v in error["notices"]):
                        raise ValueError("system errors in validator execution")
                    info.update(reported_at=s["validatedAt"],input_locator=source,report_sha256=hashlib.sha256(raw).hexdigest())
                    notices={x["code"]:x for x in d["notices"]}
                    required=notices.get("missing_required_field",{})
                    recommended=notices.get("missing_recommended_field",{})
                    def subweights(notice,table,col):
                        samples=notice.get("sampleNotices",[])
                        if len(samples)!=int(notice.get("totalNotices",0)):
                            return None
                        return sum(s.get("filename")==table+".txt" and s.get("fieldName")==col for s in samples)
                    for table,fields in RULES.items():
                        if table+".txt" not in s["files"]:continue
                        counts=[]
                        for rule in fields:
                            if len(rule)==2:counts.append(int(notices.get("route_both_short_and_long_name_missing",{}).get("totalNotices",0)))
                            else:counts.append(subweights(recommended if rule==("trip_headsign",) else required,table,rule[0]))
                        ok=all(x is not None for x in counts)
                        out.append(dict(**info,table=table,stated_rows=int(s["counts"][table.title()]),observed=json.dumps(counts),status="ok" if ok else "censored",reason="" if ok else "notice list capped"))
                except Exception as exc:out.append(dict(**info,status="excluded",reason=f"{type(exc).__name__}: {exc}"[:240]))
    path=BASE/"projected";path.mkdir(exist_ok=True)
    pd.DataFrame(out).to_csv(path/f"{rid}.tsv.gz",sep="\t",index=False)
    return rid,len(out)

def combine():
    inputs=pd.read_csv(BASE/"inputs.tsv",sep="\t",dtype={"generation":str})
    confirmed=inputs[inputs.status.eq("ok")].copy()
    reports=pd.concat([pd.read_csv(f,sep="\t") for f in (BASE/"projected").glob("*.tsv.gz")],ignore_index=True)
    reports["reported_at"]=pd.to_datetime(reports.reported_at,utc=True,format='mixed')
    scoped=reports.merge(confirmed[['feed','table','rows','expected','required','prefix','generation']],on=['feed','table'],how='inner')
    scoped['verified']=scoped.status.eq('ok')&scoped.reported_at.notna()&scoped.stated_rows.eq(scoped.rows)&scoped.observed.eq(scoped.expected)
    weekly_jobs=loads((BASE/'runs.json').read_bytes())['workflow_runs']
    expected_ids={(job['id'],variant) for job in weekly_jobs if job['conclusion']=='success'
                  for variant in ('latest','reference')}
    manifest=[]
    for (feed,table),g in scoped.groupby(['feed','table']):
        ok=g[g.verified].sort_values(['reported_at','run','variant'])


        if len(g)!=len(ok) or len(ok)<2:
            manifest.append(dict(feed=feed,table=table,status="excluded",encountered=len(g),matched=len(ok),row_mismatches=int((~g.stated_rows.eq(g.rows)).sum()),count_mismatches=int((g.status.eq("ok")&~g.observed.eq(g.expected)).sum()),censored=int(g.status.eq("censored").sum())))
            continue
        ids=set(zip(ok.run,ok.variant))
        if ids!=expected_ids or len(ok)!=len(expected_ids):
            manifest.append(dict(feed=feed,table=table,status="excluded",encountered=len(expected_ids),matched=len(ok),reason='report variants missing'))
            continue
        head=ok.iloc[0];prefix=Path(head.prefix);req=json.loads(head.required)
        line=["request_id\tl\tr\tmust_null\tmust_present"]
        for ID in range(1,len(ok)+1):
            for mask in req:line.append(f"{ID}\t0\t{int(head.rows)}\t{mask}\t0")
        prefix.with_suffix('.tsv').write_text("\n".join(line)+"\n",encoding='utf8')
        ok.assign(request_id=range(1,len(ok)+1))[['request_id','run','variant','reported_at','input_locator','report_sha256','observed']].to_csv(prefix.with_suffix('.provenance.tsv'),sep='\t',index=False)
        manifest.append(dict(feed=feed,table=table,status='ok',prefix=str(prefix),rows=int(head.rows),requests=len(ok),checks_per_request=len(req),jobs=ok.run.nunique(),first=ok.reported_at.min(),last=ok.reported_at.max(),observed=head.observed))
    pd.DataFrame(manifest).to_csv(BASE/'manifest.tsv',sep='\t',index=False)
    scoped.groupby(['status','verified'],dropna=False).size().rename('records').to_csv(BASE/'coverage.tsv',sep='\t')
    print(pd.DataFrame(manifest).groupby(['status','table']).size())

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument('--combine-only',action='store_true')
    parser.add_argument('--extract-only',action='store_true')
    args=parser.parse_args()
    jobs=[v for v in loads((BASE/'runs.json').read_bytes())['workflow_runs'] if v['conclusion']=='success']
    if not args.combine_only:
        with concurrent.futures.ProcessPoolExecutor(3) as exe:
            for result in exe.map(extract_job,jobs):print(result,flush=True)
    if not args.extract_only:combine()
