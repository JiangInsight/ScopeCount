
import concurrent.futures
import json
import urllib.parse
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from pan import RangeFile, get_session, sha, save_json
from ci_download import BASE

RULES={
    "routes":[("route_id",),("route_type",),("route_short_name","route_long_name")],
    "trips":[("trip_id",),("route_id",),("service_id",),("trip_headsign",)],
}
FIELDS={
    "routes":["route_id","route_type","route_short_name","route_long_name"],
    "trips":["trip_id","route_id","service_id","trip_headsign"],
}
START=pd.Timestamp("2026-11-01 00:00:00",tz="UTC")

def inputs(item):
    feed,url=item
    row={"feed":feed,"alias":url}
    try:
        assert url==f"https://files.mobilitydatabase.org/{feed}/latest.zip"
        r=get_session().head(url,allow_redirects=True,timeout=(10,30));r.raise_for_status()
        g=int(r.headers["x-goog-generation"])
        gen=pd.Timestamp(g,unit="us",tz="UTC")
        modified=pd.Timestamp(r.headers["Last-Modified"])
        immutable=f"https://storage.googleapis.com/mobilitydata-datasets-prod/{feed}/latest.zip?generation={g}"
        row.update(generation=g,object_time=gen.isoformat(),last_modified=modified.isoformat(),etag=r.headers.get("ETag",""),immutable=immutable,object_bytes=int(r.headers["Content-Length"]))
        if max(gen,modified)>=START:raise ValueError("object replaced after study began")
        h=get_session().head(immutable,timeout=(10,30));h.raise_for_status()
        if h.headers.get("x-goog-generation")!=str(g) or h.headers.get("ETag")!=row["etag"]:raise ValueError("versioned object differs")
        local=BASE/"feeds"/feed;local.mkdir(exist_ok=True,parents=True)
        with zipfile.ZipFile(RangeFile(immutable)) as archive:
            result=[]
            for table in RULES:
                base=dict(row,table=table)
                try:
                    matches=[v for v in archive.namelist() if v.lower().split("/")[-1]==table+".txt" and not v.startswith("__MACOSX/")]
                    if len(matches)!=1:raise ValueError("table absent or ambiguous")
                    raw=archive.read(matches[0])
                    import io
                    df=pd.read_csv(io.BytesIO(raw),dtype=str,encoding="utf-8-sig",keep_default_na=False)
                    if not len(df):raise ValueError("empty table")
                    cols=list(df.columns)
                    if len(cols)>63:raise ValueError("width exceeds 63")
                    for c in FIELDS[table]:
                        if c not in cols:
                            if table=="routes" and c in ("route_short_name","route_long_name"):
                                cols.append(c);df[c]=""
                            else:raise ValueError(f"no {c} column")
                    if len(cols)>63:raise ValueError("width exceeds 63")
                    masks=np.zeros(len(df),np.uint64)
                    for i,col in enumerate(cols):masks|=df[col].eq("").to_numpy().astype('uint64')<<np.uint64(i)
                    req=[sum(1<<cols.index(c) for c in fields) for fields in RULES[table]]
                    truth=[int(np.count_nonzero((masks & q)==q)) for q in req]
                    path=local/table
                    masks.astype("<u8").tofile(path.with_suffix(".rows"))
                    result.append(dict(base,status="ok",prefix=str(path),rows=len(df),member=matches[0],table_sha256=sha(raw),mask_sha256=sha(masks.astype("<u8").tobytes()),fields=json.dumps(cols),required=json.dumps(req),expected=json.dumps(truth)))
                except Exception as e:
                    result.append(dict(base,status="excluded",reason=f"{type(e).__name__}: {e}"[:350]))
        return result
    except Exception as e:
        return [dict(row,status="excluded",reason=f"{type(e).__name__}: {e}"[:350])]

if __name__=="__main__":
    f=BASE/"metadata.zip"
    if not f.exists():
        f=next(BASE.glob("*.meta.zip"))
    meta=json.loads(zipfile.ZipFile(f).read("gtfs_latest_versions.json"))
    out=[]
    with concurrent.futures.ThreadPoolExecutor(10) as exe:
        for i,result in enumerate(exe.map(inputs,sorted(meta.items())),1):
            out.extend(result)
            if i%40==0 or i==len(meta):
                pd.DataFrame(out).to_csv(BASE/"inputs.tsv",sep="\t",index=False)
                print(i,len(meta),sum(v['status']=='ok' for v in out),flush=True)
