
from __future__ import annotations
import argparse, csv, hashlib, itertools, os, random, time
from pathlib import Path
import numpy as np
import pyarrow as pa
import duckdb

HERE=Path(__file__).resolve().parent
EXT=Path(os.environ.get('SCOPECNT_EXTENSION',str(HERE.parents[2]/'compiled'/'duckdb155_final'/'scopecount.duckdb_extension')))
DEFAULT=('tree_direct','bitmap_direct','online_direct','tree_direct_memo','bitmap_direct_memo','online_direct_memo','tree','independent','bitmap','lazy','words','leaf','synopsis','sql','sql_opt','sql_memo','sql_opt_memo','tree_memo','bitmap_memo')
DETAIL=('compile_ns','kernel_ns','plan_hits','predicate_hits','new_predicates','terms','base_bytes','cache_bytes')
SUPPORTED=DEFAULT+('roaring_direct','roaring_direct_memo')
clock=time.perf_counter_ns

def connect():
    con=duckdb.connect(config={'allow_unsigned_extensions':'true','threads':'1'})
    path=str(EXT.resolve()).replace("'","''")
    con.execute(f"LOAD '{path}'")
    return con

def read_trace(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as src:
        records=csv.DictReader(src,delimiter='\t')
        wanted={'request_id','l','r','must_null','must_present'}
        if not wanted.issubset(records.fieldnames or []):raise ValueError(f'expected TSV fields {sorted(wanted)}')
        out=[]
        for name,g in itertools.groupby(records,key=lambda row:row['request_id']):
            group=list(g);l=int(group[0]['l']);r=int(group[0]['r'])
            if any(int(row['l'])!=l or int(row['r'])!=r for row in group):raise ValueError('inconsistent bounds in one request')
            out.append((name,l,r,tuple((int(row['must_null']),int(row['must_present'])) for row in group)))
        return out

def validate(rows, requests):
    if len(rows)>=2**32-1:raise ValueError('row count must be below UINT32_MAX')
    seen=set();used=int(np.bitwise_or.reduce(rows,initial=np.uint64(0)));out=[]
    for name,l,r,qs in requests:
        if name in seen or not (0<=l<=r<=len(rows)):raise ValueError('duplicate request identifier or invalid endpoint')
        if not qs:raise ValueError('request has zero outputs')
        seen.add(name)
        rules=tuple((int(p),int(n)) for p,n in qs)
        for one,zero in rules:
            if not(0<=one<2**64 and 0<=zero<2**64):raise ValueError('mask exceeds 64 bits')
            used|=one|zero
        out.append((name,l,r,rules))
    if not out:raise ValueError('empty trace')
    return [j for j in range(64) if used>>j&1],out

def install_table(con,rows,fields):
    start=clock();ones=np.ones(len(rows),dtype=np.bool_)
    table=pa.table({'rid':pa.array(np.arange(len(rows),dtype=np.uint32)),**{
        f'c{j}':pa.array(ones,mask=((rows>>j)&1).astype(np.bool_)) for j in fields}})
    con.register('sc_input_arrow',table)
    try:con.execute('CREATE OR REPLACE TEMP TABLE scope_data AS SELECT * FROM sc_input_arrow')
    finally:con.unregister('sc_input_arrow')
    return clock()-start

def condition(one,zero,fields):
    if one&zero:return 'FALSE'
    rules=[f'c{j} IS '+('NULL' if one>>j&1 else 'NOT NULL') for j in fields if (one|zero)>>j&1]
    return ' AND '.join(rules) or 'TRUE'

def native_sql(rules,fields):
    sel=', '.join('count(*) FILTER (WHERE '+condition(a,b,fields)+')' for a,b in rules)
    return f'SELECT [{sel}] FROM scope_data WHERE rid >= $1::UINTEGER AND rid < $2::UINTEGER'

def optimized_sql(rules,fields,whole):
    expr=[]
    for one,zero in rules:
        bits=one|zero
        if one&zero:expr.append('0::BIGINT')
        elif not bits:expr.append('count(*)')
        elif bits.bit_count()==1:
            count=f'count(c{bits.bit_length()-1})'
            expr.append('count(*)-'+count if one else count)
        else:expr.append('count(*) FILTER (WHERE '+condition(one,zero,fields)+')')
    return 'SELECT ['+','.join(expr)+'] FROM scope_data'+('' if whole else ' WHERE rid >= $1::UINTEGER AND rid < $2::UINTEGER')

def synopsis_sql(rules,fields):
    out=[]
    for one,zero in rules:
        if one&zero:out.append('0::BIGINT')
        elif one|zero==0:out.append('n')
        elif (one|zero).bit_count()>1:return None
        else:
            j=(one|zero).bit_length()-1
            out.append(f'n-x{j}' if one else f'x{j}')
    return 'SELECT ['+','.join(out)+'] FROM scope_summary'

def unique_results(con, requests, fields):

    gold={}
    templates={}
    for _,l,r,rules in requests:
        key=(l,r,rules)
        if key not in gold:
            if rules not in templates:templates[rules]=native_sql(rules,fields).replace('$1','?').replace('$2','?')
            gold[key]=tuple(map(int,con.execute(templates[rules],[l,r]).fetchone()[0]))
    return gold

def measure(con, requests, fields, rows, method, common_load, gold, rep, slot, dataset):
    memoized=method.endswith('_memo');kind=method.removesuffix('_memo')
    handle=None;native_build=0;base_bytes=0;prep={};memo={};records=[];history_positions=[]
    start=clock()
    if kind.endswith('_direct'):
        agg=','.join(f'scope_validity(rid,c{j})' for j in fields)
        indices=','.join(map(str,fields));name=kind.removesuffix('_direct')
        sql=f"SELECT scope_attach('{name}',count(*)::UINTEGER,[{indices}]::UBIGINT[],[{agg}]::BLOB[]) FROM scope_data"
        handle=int(con.execute(sql).fetchone()[0])
    elif kind=='synopsis':
        sel=['count(*) AS n']+[f'count(c{j}) AS x{j}' for j in fields]
        con.execute('CREATE OR REPLACE TEMP TABLE scope_summary AS SELECT '+','.join(sel)+' FROM scope_data')
        base_bytes=8*(1+len(fields))
    elif kind not in ('sql','sql_opt'):
        pack=' | '.join(f'(CAST(c{j} IS NULL AS UBIGINT) << {j})' for j in fields) or '0::UBIGINT'
        handle=int(con.execute(f"SELECT scope_build('{kind}',coalesce(list(({pack}) ORDER BY rid),[]::UBIGINT[])) FROM scope_data").fetchone()[0])
    build=0 if kind in ('sql','sql_opt') else clock()-start
    if handle is not None:
        stat=con.execute(f'SELECT scope_stats({handle}::UBIGINT)').fetchone()[0]
        base_bytes,native_build=map(int,(stat[6],stat[8]))
        con.execute(f'SELECT scope_profile({handle}::UBIGINT)')
    try:
        for order,(name,l,r,rules) in enumerate(requests,1):
            start=clock();sql_prepare=0;memo_hits=0
            if memoized:
                missing=[]
                for rule in rules:
                    if (l,r,rule) in memo:memo_hits+=1
                    elif rule not in missing:missing.append(rule)
                needed=tuple(missing)
            else:needed=rules
            if needed:
                full_synopsis=kind=='synopsis' and l==0 and r==rows and all((p&n) or (p|n).bit_count()<=1 for p,n in needed)
                nolimits=full_synopsis or (kind=='sql_opt' and l==0 and r==rows)
                prepkey=needed,nolimits
                if prepkey not in prep:
                    pt=clock()
                    stmt='sc_req_'+str(len(prep));prep[prepkey]=stmt
                    if kind=='sql_opt':cmd=optimized_sql(needed,fields,nolimits)
                    elif kind in ('sql','synopsis'):
                        cmd=synopsis_sql(needed,fields) if full_synopsis else native_sql(needed,fields)
                    else:
                        lmask='['+','.join(str(p)+'::UBIGINT' for p,_ in needed)+']'
                        rmask='['+','.join(str(n)+'::UBIGINT' for _,n in needed)+']'
                        cmd=f'SELECT scope_count({handle}::UBIGINT,$1::UINTEGER,$2::UINTEGER,{lmask},{rmask})'
                    con.execute('PREPARE '+stmt+' AS '+cmd)
                    sql_prepare=clock()-pt
                stmt=prep[prepkey]
                arglist='' if nolimits else f'({l},{r})'
                actual=tuple(map(int,con.execute(f'EXECUTE {stmt}{arglist}').fetchone()[0]))
                if memoized:
                    memo.update({(l,r,rule):val for rule,val in zip(needed,actual)})
                if handle is not None:history_positions.append(len(records))
            if memoized:actual=tuple(memo[(l,r,rule)] for rule in rules)
            took=clock()-start
            if actual!=gold[(l,r,rules)]:raise AssertionError((dataset,name,method,actual,gold[(l,r,rules)]))
            records.append(dict(dataset=dataset,backend=method,rep=rep,backend_order=slot,ordinal=order,request_id=name,
                rows=rows,field_count=len(fields),l=l,r=r,rules=len(rules),load_ns=common_load,index_build_ns=build,
                native_build_ns=native_build,request_ns=took,sql_prepare_ns=sql_prepare,compile_ns=0,kernel_ns=0,
                plan_hits=0,predicate_hits=0,new_predicates=0,terms=0,base_bytes=base_bytes,cache_bytes=0,
                result_cache_hits=memo_hits,result_cache_entries=len(memo),results=','.join(map(str,actual))))
        if handle is not None:
            hist=con.execute(f'SELECT scope_history({handle}::UBIGINT)').fetchone()[0]
            if len(hist)!=len(history_positions)*len(DETAIL):raise AssertionError('inconsistent extension call count')
            for i,pos in enumerate(history_positions):records[pos].update(zip(DETAIL,map(int,hist[i*8:(i+1)*8])))
            last=0
            for row in records:
                if row['result_cache_hits']==row['rules']:row['cache_bytes']=last
                else:last=row['cache_bytes']
    finally:
        for stmt in prep.values():con.execute('DEALLOCATE '+stmt)
        if handle is not None:con.execute(f'SELECT scope_drop({handle}::UBIGINT)')
        if kind=='synopsis':con.execute('DROP TABLE scope_summary')
    return records

def execution_orders(methods,repeats,dataset,balanced):
    if not balanced:
        rng=random.Random(99117)
        for _ in range(repeats):
            order=list(methods);rng.shuffle(order);yield order
        return


    seed=hashlib.sha256(('scope5-balanced-order:'+dataset).encode()).digest()
    rng=random.Random(int.from_bytes(seed[:8],'big'))
    for block in range(0,repeats,len(methods)):
        base=list(methods);rng.shuffle(base)
        rotations=list(range(len(methods)));rng.shuffle(rotations)
        for start in rotations[:repeats-block]:
            yield base[start:]+base[:start]

def run(rows, requests, repeats=5, methods=None, con=None, dataset='snapshot',balanced=False):

    own=con is None
    if own:con=connect()
    try:
        if isinstance(rows,(Path,str)):
            p=Path(rows)
            if p.stat().st_size%8:raise ValueError('truncated uint64 input')
            rows=np.fromfile(p,dtype='<u8')
        else:rows=np.asarray(rows,dtype=np.uint64)
        if rows.ndim!=1:raise ValueError('expected 1-D row signatures')
        if isinstance(requests,(Path,str)):requests=read_trace(requests)
        fields,requests=validate(rows,requests);n=len(rows)
        methods=tuple(DEFAULT if methods is None else methods)
        if not methods or len(set(methods))!=len(methods) or set(methods)-set(SUPPORTED):raise ValueError('invalid backend list')
        if repeats<1:raise ValueError('empty repetition count')
        common_load=install_table(con,rows,fields)
        gold=unique_results(con,requests,fields)
        elapsed=[]
        for rep,order in enumerate(execution_orders(methods,repeats,dataset,balanced)):
            for slot,method in enumerate(order):
                elapsed.extend(measure(con,requests,fields,n,method,common_load,gold,rep,slot,dataset))
        return elapsed
    finally:
        if own:con.close()

def save(rows,path):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix(path.suffix+'.tmp')
    with tmp.open('w',newline='',encoding='utf8') as out:
        writer=csv.DictWriter(out,fieldnames=list(rows[0]),delimiter='\t')
        writer.writeheader();writer.writerows(rows)
    tmp.replace(path)
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('rows',type=Path);p.add_argument('trace',type=Path);p.add_argument('out',type=Path)
    p.add_argument('repeats',type=int,nargs='?',default=5);p.add_argument('--methods',nargs='+',choices=SUPPORTED)
    a=p.parse_args();save(run(a.rows,a.trace,a.repeats,a.methods,dataset=a.rows.stem),a.out)
