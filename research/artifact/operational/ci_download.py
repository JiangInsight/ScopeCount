


import concurrent.futures
import hashlib
import json
from pathlib import Path
import requests
from pan import BASE as PAN,fetch,save_json
BASE=PAN.parent/"ci"
WINDOW="2026-11-01..2026-11-07"
ORG="MobilityData/gtfs-validator"
WORKFLOW=f"https://api.github.com/repos/{ORG}/actions/workflows/acceptance_test.yml/runs"

def download(run):
    rid=run["id"]
    loc=BASE/f"{rid}.artifacts.json"
    if not loc.exists():save_json(loc,fetch(run["artifacts_url"]).json())
    items=json.loads(loc.read_bytes())["artifacts"]
    out=[]
    for name in ("reports_all","datasets_metadata"):
        match=next((x for x in items if x["name"]==name and not x["expired"]),None)
        if not match:raise ValueError(f"missing retained {rid} {name}")
        url=f"https://nightly.link/{ORG}/actions/runs/{rid}/{name}.zip"
        p=BASE/f"{rid}{'.meta' if name=='datasets_metadata' else ''}.zip"
        if not p.exists():
            import time
            for attempt in range(3):
                resp=requests.get(url,timeout=(15,180),stream=True)
                if resp.ok:break
                time.sleep(attempt+1)
            resp.raise_for_status()
            tmp=p.with_suffix('.part')
            with tmp.open('wb') as f:
                for chunk in resp.iter_content(1<<19):f.write(chunk)
            tmp.replace(p)
        h=hashlib.sha256(p.read_bytes()).hexdigest()
        assert match["digest"]=="sha256:"+h and p.stat().st_size==match["size_in_bytes"],(rid,name,h,match["digest"])
        out.append({"run":rid,"timestamp":run["created_at"],"head":run["head_sha"],"workflow":run["html_url"],"artifact":name,"artifact_id":match["id"],"sha256":h,"access_url":url})
    return out

if __name__=="__main__":
    BASE.mkdir(exist_ok=True,parents=True)
    f=BASE/"runs.json"
    if not f.exists():save_json(f,fetch(WORKFLOW,params={"per_page":100,"created":WINDOW}).json())
    d=json.loads(f.read_bytes());assert d["total_count"]==len(d["workflow_runs"])
    runs=[r for r in d["workflow_runs"] if r["conclusion"]=="success"];out=[]
    with concurrent.futures.ThreadPoolExecutor(4) as exe:
        for ix,res in enumerate(exe.map(download,runs)):
            out+=res;print(ix+1,len(runs),flush=True)
    save_json(BASE/"artifacts.json",out)
