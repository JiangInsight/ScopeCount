
from argparse import ArgumentParser
from pathlib import Path
import pandas as pd


def evidence(source):
    t = pd.read_csv(source, sep="\t", dtype={"keep_mask": str, "digest": str})
    keys = ["dataset", "first", "width", "horizon"]
    methods = ["cache", "tree", "cut"]
    if t.duplicated(keys+["method","rep"]).any() or set(t.method)!=set(methods):
        raise ValueError("Duplicate or missing policies")
    g=t.groupby(keys)
    if not (g.size()==9).all() or not (g.digest.nunique()==1).all():
        raise ValueError("Missing repetition or count discrepancy")
    if (t[t.method.eq("tree")].cache_bytes!=0).any():
        raise ValueError("Unexpected tree materialization")
    t["prepared"]=t.price_ns+t.cut_ns+t.setup_ns+t.exec_ns
    t["fresh"]=t.prepared+t.union_ns.where(t.method.ne("cache"),0)
    m=t.groupby(keys+["method"])[["prepared","fresh","cache_bytes","kept"]].median().reset_index()
    result=pd.DataFrame(index=m[keys].drop_duplicates().set_index(keys).index)
    for col in ["prepared","fresh","cache_bytes","kept"]:
        w=m.pivot(index=keys,columns="method",values=col)
        for k in methods:result[col+"_"+k]=w[k]
    for col in ["prepared","fresh"]:
        v=result[[col+"_cache",col+"_tree"]].min(axis=1)
        result[col+"_speed"]=v/result[col+"_cut"]
        result[col+"_win"]=result[col+"_cut"]<v


        dom=pd.Series(False,index=result.index)
        for k in ["cache","tree"]:
            t1,s1=result[col+"_"+k],result["cache_bytes_"+k]
            t2,s2=result[col+"_cut"],result.cache_bytes_cut
            dom |= (t1<=t2)&(s1<=s2)&((t1<t2)|(s1<s2))
        result[col+"_nd"]=~dom
    result=result.reset_index()
    result["mixed"]=(result.kept_cut>0)&(result.kept_cut<result.width)
    return t,result


def count(n):
    return f"{int(n):,}"


def main():
    root=Path(__file__).resolve().parents[1]
    parser=ArgumentParser()
    parser.add_argument("source",nargs="?",type=Path,default=root.parent/"runs"/"cut_execution.tsv")
    parser.add_argument("--out",type=Path,default=root/"cut_exec_numbers.tex")
    a=parser.parse_args()
    raw,z=evidence(a.source)
    if z.dataset.nunique()!=8 or set(z.width)!={16,32,64} or set(z.horizon)!={1,24,384}:
        raise ValueError("Incomplete real-data wide benchmark")
    mixed=z[z.mixed]

    saved=(z.cache_bytes_cut<z.cache_bytes_cache)
    vals=dict(ExecSeries=count(len(z)),ExecBundles=count(len(z.drop_duplicates(["dataset","first","width"]))),
              ExecMixed=count(len(mixed)),ExecPreparedWins=count(z.prepared_win.sum()),ExecFreshWins=count(z.fresh_win.sum()),
              ExecPreparedND=count(z.prepared_nd.sum()),ExecFreshND=count(z.fresh_nd.sum()),
              ExecSavings=count(saved.sum()),ExecMixedWins=count(mixed.prepared_win.sum()),
              ExecPreparedRatio=f"{z.prepared_speed.median():.2f}",ExecFreshRatio=f"{z.fresh_speed.median():.2f}",
              ExecReps=count(len(raw)),ExecCells=count((raw.horizon*raw.width).sum()))
    trade=mixed[(mixed.prepared_cut<mixed.prepared_tree) & (mixed.cache_bytes_cut<mixed.cache_bytes_cache)]
    vals.update(ExecTrade=count(len(trade)),ExecTradeSpeed=f"{(trade.prepared_tree/trade.prepared_cut).median():.2f}",
                ExecTradeBytes=f"{100*(1-trade.cache_bytes_cut/trade.cache_bytes_cache).median():.1f}")
    source="% Generated from cut_execution.tsv by artifact/cut_execution_tables.py\n"
    source+="".join(r"\newcommand{\%s}{%s}"%(k,v)+"\n" for k,v in vals.items())
    a.out.write_text(source,encoding="utf-8")
    print(z.groupby("horizon")[["prepared_win","fresh_win","prepared_nd","fresh_nd","mixed"]].sum().to_string())
    print("medians",z.groupby("horizon")[["prepared_speed","fresh_speed"]].median().to_string())
    print("whole",vals)


if __name__=="__main__":main()
