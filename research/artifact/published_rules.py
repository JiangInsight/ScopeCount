
from pathlib import Path
import argparse, hashlib, io, subprocess
import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup

BASE = Path(__file__).resolve().parents[2]
CYCLES = ((2013,"H"),(2015,"I"),(2017,"J"))
RULES = (
    ("asthma","MCQ010","MCQ025"),
    ("current_asthma","MCQ035","MCQ040"),
    ("transfusion","MCQ092","MCD093"),
    ("menarche","MCQ149","MCQ151"),
    ("jaundice","MCQ203","MCQ206"),
    ("cancer","MCQ220","MCQ230A"),
)

def fetch(url, directory):
    p = directory / url.rsplit("/",1)[1]
    if not p.exists():
        response = requests.get(url,timeout=90)
        response.raise_for_status()
        tmp=p.with_suffix(p.suffix+".tmp")
        tmp.write_bytes(response.content)
        tmp.replace(p)
    raw=p.read_bytes()
    return raw,hashlib.sha256(raw).hexdigest()

def parse_book(raw):
    records={}
    for section in BeautifulSoup(raw,"html.parser").select("div.pagebreak"):
        h=section.find("h3")
        if h is None or section.find("table") is None:
            continue
        key=h.get_text(" ",strip=True).split(" - ")[0].upper()
        values={}
        for row in section.find("table").select("tr"):
            cells=[td.get_text(" ",strip=True) for td in row.find_all("td")]
            if len(cells)==5:
                values[cells[0]]=(cells[1],int(cells[2].replace(",","")),cells[4].upper())
        records[key]=values
    return records

def fingerprint(matrix):
    value=0
    for x in matrix.ravel():
        value=(value*131+int(x)) & ((1<<64)-1)
    return str(value)

def build(cache,prefix,out):
    counts=[];manifest=[];parts=[];ranges=[];cursor=0
    for year,tag in CYCLES:
        stub=f"https://wwwn.cdc.gov/Nchs/Data/Nhanes/Public/{year}/DataFiles/MCQ_{tag}"
        xpt,sha=fetch(stub+".xpt",cache);html,booksha=fetch(stub+".htm",cache)
        data=pd.read_sas(io.BytesIO(xpt),format="xport");data.columns=data.columns.str.upper()
        codes=parse_book(html);order=list(codes)
        masks=np.zeros(len(data),dtype="<u8")
        for i,(rule,gate,child) in enumerate(RULES):
            status=codes[gate];follow=codes[child]; gate_values=data[gate];child_values=data[child]


            destinations={status[k][2] for k in ("2","7","9")}
            if (len(destinations)!=1 or "" in destinations or status["1"][2] or
                order.index(child)!=order.index(gate)+1 or order.index(next(iter(destinations)))<=order.index(child)):
                raise ValueError((year,rule,destinations))
            if {str(int(v)) for v in gate_values.dropna()}-{"1","2","7","9"}:
                raise ValueError("Unexpected screening code")
            for k in ("1","2","7","9"):
                if int(gate_values.eq(int(k)).sum())!=status[k][1]:
                    raise ValueError((year,gate,k))
            if int(gate_values.isna().sum())!=status["."][1] or int(child_values.isna().sum())!=follow["."][1]:
                raise ValueError((year,rule,"marginal counts disagree with release"))
            skip=gate_values.isin([2,7,9]);alive=child_values.notna()
            masks|=gate_values.isna().to_numpy(dtype=np.uint64)<<(2*i)
            masks|=child_values.isna().to_numpy(dtype=np.uint64)<<(2*i+1)
            unknown={int(k) for k,v in follow.items() if k.isdecimal() and v[0].lower() in {"refused","don't know","don’t know"}}
            counts.append(dict(cycle=f"{year}-{str(year+1)[-2:]}",rule=rule,gate=gate,child=child,
                jump=next(iter(destinations)),rows=len(data),yes=int(gate_values.eq(1).sum()),no=int(gate_values.eq(2).sum()),
                refused=int(gate_values.eq(7).sum()),dont_know=int(gate_values.eq(9).sum()),gate_missing=int(gate_values.isna().sum()),
                follow_present=int(alive.sum()),follow_refused_or_unknown=int(child_values.isin(unknown).sum()),
                pair_recorded=int((gate_values.notna() & alive).sum()),orphan=int((gate_values.isna() & alive).sum()),
                skipped_code_follow_recorded=int((skip & alive).sum()),yes_follow_absent=int((gate_values.eq(1) & ~alive).sum())))
        parts.append(masks);ranges.append((cursor,cursor+len(data)));cursor+=len(data)
        manifest.append(dict(cycle=year,rows=len(data),data_url=stub+".xpt",data_sha256=sha,
                             codebook_url=stub+".htm",codebook_sha256=booksha,mask_sha256=hashlib.sha256(masks.tobytes()).hexdigest()))
    np.concatenate(parts).tofile(prefix.with_suffix(".rows"))
    with prefix.with_suffix(".queries").open("w",encoding="ascii") as f:
        for group in ("orphan","pair"):
            for i,(label,_,_) in enumerate(RULES):
                gate=1<<(2*i);child=1<<(2*i+1)
                one,zero=(gate,child) if group=="orphan" else (0,gate|child)
                for l,r in ranges:f.write(f"{group}-{label} {one} {zero} {l} {r}\n")
    pd.DataFrame(manifest).to_csv(out/"publisher_sources.tsv",sep="\t",index=False)
    numbers=pd.DataFrame(counts)
    numbers.to_csv(out/"publisher_counts.tsv",sep="\t",index=False)
    return numbers

def main():
    p=argparse.ArgumentParser();p.add_argument("--cache",type=Path,default=BASE/"data"/"published_mcq")
    p.add_argument("--binary",type=Path,default=BASE/"compiled"/"published_run.exe")
    p.add_argument("--derive-only",action="store_true")
    p.add_argument("--summarize-only",action="store_true",help="Reuse the timing log and verify its digests")
    p.add_argument("--frozen-tables",action="store_true",help="Regenerate macros from the archived counts and timing log, without contacting the publisher")
    args=p.parse_args()
    args.cache.mkdir(exist_ok=True,parents=True);out=BASE/"runs";out.mkdir(exist_ok=True)
    prefix=args.cache/"natural"; numbers=pd.read_csv(out/"publisher_counts.tsv",sep="\t") if args.frozen_tables else build(args.cache,prefix,out)
    if args.derive_only:return
    timings=out/"publisher_times.tsv"
    if not (args.summarize_only or args.frozen_tables):
        subprocess.run([str(args.binary),str(prefix),str(timings)],check=True)
    t=pd.read_csv(timings,sep="\t",dtype={"count_digest":str})
    for group,col in (("orphan","orphan"),("pair","pair_recorded")):
        expected=fingerprint(numbers[col].to_numpy());g=t[t.workload.eq(group)]
        if set(g.count_digest)!={expected} or len(g)!=303 or g.duplicated(["method","rep"]).any():
            raise ValueError("Timing results differ from official-source row oracle")
    t["total_ns"]=t.compile_ns+t.exec_ns
    summary=t.groupby(["workload","method"],as_index=False)[["compile_ns","exec_ns","total_ns","index_ns","ranks","updates"]].median()
    summary.to_csv(out/"publisher_summary.tsv",sep="\t",index=False)
    cycle_totals=numbers.groupby("cycle").pair_recorded.sum().tolist()
    pair=summary.loc[summary.workload.eq("pair")].set_index("method")
    if pair.loc["joint","ranks"]!=pair.loc["scalar","ranks"] or pair.loc["cache","exec_ns"]>=pair.loc["joint","exec_ns"]:
        raise AssertionError("Manuscript timing or work comparison requires revision")
    if numbers.orphan.sum() or numbers.skipped_code_follow_recorded.sum():
        raise AssertionError("Manuscript absence claims require revision")
    values={"PubRows":numbers.groupby("cycle").rows.first().sum(),"PubFirst":cycle_totals[0],
            "PubSecond":cycle_totals[1],"PubThird":cycle_totals[2],"PubReads":pair.loc["joint","ranks"]}
    tex="".join(chr(92)+"newcommand{"+chr(92)+k+"}{"+f"{int(v):,}"+"}"+chr(10) for k,v in values.items())
    (Path(__file__).resolve().parents[1]/"publisher_numbers.tex").write_text(tex,encoding="utf-8")
    print(summary.to_string(index=False))
    print(numbers.groupby("cycle")[["pair_recorded","orphan","skipped_code_follow_recorded","yes_follow_absent"]].sum())
    print(numbers[numbers.rule.eq("transfusion")].to_string(index=False))

if __name__=="__main__":
    main()
