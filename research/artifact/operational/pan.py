



import argparse
import concurrent.futures
import datetime as dt
import hashlib
import io
import json
import re
import threading
import zipfile
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE = Path(__file__).resolve().parents[3] / "traces" / "transport"
CATALOG = "https://transport.data.gouv.fr/api/datasets"
PROVIDER = "transport-data-gouv-fr-resource-history-prod.cellar-c2.services.clever-cloud.com"
LOCAL = threading.local()
METRICS = {
    "routes": [("route_short_name", "routes_with_short_name_count"),
               ("route_long_name", "routes_with_long_name_count")],
    "trips": [("trip_headsign", "trips_with_trip_headsign_count"),
              ("shape_id", "trips_with_shape_count")],
}

def sha(data):
    return hashlib.sha256(data).hexdigest()

def get_session():
    if not hasattr(LOCAL, "session"):
        session = requests.Session()
        retry = Retry(total=3, backoff_factor=.5, status_forcelist=[429,500,502,503,504])
        session.mount("https://", HTTPAdapter(max_retries=retry))
        session.headers["User-Agent"] = "ScopeCount academic reproduction (read-only, bounded concurrency)"
        LOCAL.session = session
    return LOCAL.session

def fetch(url, **kwargs):
    response = get_session().get(url, timeout=(12,45), **kwargs)
    response.raise_for_status()
    return response

def save_json(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf8")

class RangeFile(io.RawIOBase):

    def __init__(self, url):
        self.url = url
        tail = fetch(url, headers={"Range":"bytes=-65536"})
        if tail.status_code == 206:
            span = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)",tail.headers["Content-Range"])
            start, end, self.length = map(int,span.groups())
            if len(tail.content)!=end-start+1: raise ValueError("truncated ZIP tail")
        else:
            start = 0
            self.length = len(tail.content)
        self.p = 0
        self.blocks = [(start,tail.content)]
    def readable(self):return True
    def seekable(self):return True
    def tell(self):return self.p
    def seek(self, offset, whence=0):
        self.p = offset + (0,self.p,self.length)[whence]
        if self.p < 0: raise OSError("negative seek")
        return self.p
    def read(self, length=-1):
        if length<0: length=self.length-self.p
        end=min(self.length,self.p+length)
        if end<=self.p:return b""
        for start,data in self.blocks:
            if start<=self.p and end<=start+len(data):break
        else:
            start=self.p
            last=min(self.length,max(end,self.p+32768))-1
            response=fetch(self.url,headers={"Range":f"bytes={start}-{last}"})
            data=response.content
            if response.status_code==200:start=0
            elif response.headers.get('Content-Range')!=f'bytes {start}-{last}/{self.length}':
                raise ValueError("invalid HTTP Range")
            self.blocks.append((start,data))
        out=data[self.p-start:end-start]
        if len(out)!=end-self.p:raise ValueError("partial download")
        self.p=end
        return out

def report_info(html):
    soup=BeautifulSoup(html,"html.parser")
    for link in soup.find_all("a",href=True):
        if urlsplit(link["href"]).netloc!=PROVIDER:continue
        line=" ".join(link.parent.stripped_strings)

        stamp=re.search(r"le (\d{2}/\d{2}/\d{4}) à (\d{2})h(\d{2}) Europe/Paris", line)
        if stamp and "Validation effectuée" in line:
            day,h,m=stamp.groups()
            time=dt.datetime.strptime(day+h+m,"%d/%m/%Y%H%M").replace(tzinfo=ZoneInfo("Europe/Paris"))
            return link["href"],time.isoformat(),line
    raise ValueError("no timed validation bound to immutable snapshot")

def run_resource(payload):
    x,r=payload
    rid=str(r["id"]); path=BASE/"resources"/rid;path.mkdir(parents=True,exist_ok=True)
    row={"resource":rid,"dataset":x["id"],"dataset_title":x["title"],"resource_title":r["title"],"license":str(x["licence"]),"report_page":r["page_url"]}
    try:
        html_path=path/"resource.html"
        if not html_path.exists():html_path.write_bytes(fetch(r["page_url"]).content)
        html=html_path.read_bytes()
        archive,timestamp,line=report_info(html)
        row.update(archive=archive,reported_at=timestamp,report_html_sha256=sha(html),report_evidence=line)
        index=zipfile.ZipFile(RangeFile(archive))
        stats=r["metadata"]["stats"]
        save_json(path/"provider.json",{"archive":archive,"reported_at":timestamp,"report_evidence":line,"report_sha256":sha(html),"dataset":x["id"],"resource":rid,"stats":stats,"validator":r["metadata"]["validator_version"],"source":CATALOG})
        result=[]
        for table,selectors in METRICS.items():
            key=table+".txt";matches=[v for v in index.namelist() if v.lower().split("/")[-1]==key and "__MACOSX/" not in v]
            if len(matches)!=1:raise ValueError(f"{key}: expected one member")
            data=index.read(matches[0])
            df=pd.read_csv(io.BytesIO(data),dtype=str,keep_default_na=False,encoding="utf-8-sig")
            df.columns=[k.strip() for k in df.columns]
            if len(df)!=stats[table+"_count"] or len(df)==0:raise ValueError(f"{key}: row count differs or zero")
            if len(df.columns)>61:raise ValueError(f"{key}: too many input columns")
            cols=list(df.columns)
            for col,_ in selectors:
                if col not in cols:
                    cols.append(col)
                    df[col]=""
            if len(cols)>63:raise ValueError(f"{key}: width")
            masks=np.zeros(len(df),np.uint64)
            for i,c in enumerate(cols):
                null=df[c].eq("").to_numpy()
                masks|=null.astype("uint64")<<np.uint64(i)
            trace=[]; truth=[]
            for c,metric in selectors:
                real=int(stats[metric]); calc=int(df[c].ne("").sum())
                if calc!=real:raise ValueError(f"{key}: observed count {metric} {real} differs from source mask {calc}")

                trace.append(f"1\t0\t{len(df)}\t0\t{1<<cols.index(c)}")
                truth.append(real)
            prefix=path/table
            masks.astype("<u8").tofile(prefix.with_suffix(".rows"))
            prefix.with_suffix(".tsv").write_text("request_id\tl\tr\tmust_null\tmust_present\n"+"\n".join(trace)+"\n",encoding="utf8")
            result.append(dict(**row,table=table,prefix=str(prefix),rows=len(df),width=len(cols),fields=json.dumps(cols),rules=",".join(c for c,_ in selectors),observed=json.dumps(truth),labels=json.dumps([m for _,m in selectors]),member=matches[0],table_sha256=sha(data),masks_sha256=sha(masks.astype("<u8").tobytes()),status="ok"))
        return result
    except Exception as ex:
        return [dict(**row,status="excluded",reason=f"{type(ex).__name__}: {ex}"[:550])]

def candidate_set(d):
    unique={}
    for x in d:
        for r in x.get("resources",[]):
            if r.get("format")=="GTFS" and r.get("is_available") and all(k in r.get("metadata",{}).get("stats",{}) for q in METRICS.values() for _,k in q):
                unique[r["id"]]=(x,r)
    return unique

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--out",type=Path,default=BASE)
    parser.add_argument("--limit",type=int,default=0,help="Zero selects the whole frozen catalog")
    parser.add_argument("--workers",type=int,default=6)
    args=parser.parse_args()
    BASE=args.out.resolve();BASE.mkdir(exist_ok=True,parents=True);p=BASE/"datasets.json"
    if not p.exists():p.write_bytes(fetch(CATALOG).content)
    unique=candidate_set(json.loads(p.read_bytes()))

    order=sorted(unique,key=lambda k:sha(str(k).encode()))
    if args.limit:order=order[:args.limit]
    rows=[]
    with concurrent.futures.ThreadPoolExecutor(args.workers) as pool:
        for i,group in enumerate(pool.map(run_resource,(unique[k] for k in order)),1):
            rows.extend(group)
            if i%10==0 or i==len(order):
                print(i,len(order),sum(v['status']=='ok' for v in rows),flush=True)
                pd.DataFrame(rows).to_csv(BASE/"manifest.tsv",sep="\t",index=False)
