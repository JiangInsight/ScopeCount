
import struct
import argparse

import duckdb
import numpy as np

from replay import connect, run


def check_aggregate(db):
    db.execute("SET threads=4")
    db.execute(
        "CREATE TEMP TABLE shuffled AS SELECT i::UINTEGER rid, "
        "CASE WHEN i%5=1 THEN NULL ELSE i%3!=0 END c "
        "FROM range(13183) s(i) ORDER BY hash(i)"
    )
    payload = db.execute("SELECT scope_validity(rid,c) FROM shuffled").fetchone()[0]
    header, *words = struct.unpack(f"<{len(payload)//8}Q", payload)
    assert header == 13183
    assert all((words[i//64] >> (i%64)) & 1 == (i%5 == 1) for i in range(header))
    for source in ("(0),(0)", "(0),(2)", "(NULL)", "(4294967295)"):
        try:
            db.execute(f"SELECT scope_validity(i::UINTEGER,TRUE) FROM (VALUES {source}) t(i)").fetchone()
        except duckdb.Error:
            continue
        raise AssertionError(f"accepted out-of-contract row identifiers {source}")
    db.execute("SET threads=1")


def check_boundaries(db):
    random = np.random.default_rng(107)
    near = (1 << 63) | 2
    methods = ["tree_direct", "bitmap_direct", "online_direct", "online_direct_memo",
               "sql_opt", "synopsis", "sql_opt_memo"]
    for n in (0,7):
        empty_schema=run(np.zeros(n,dtype=np.uint64),[("all",0,n,[(0,0)])],1,methods,db)
        assert all(record["results"]==str(n) for record in empty_schema)
    for size in (0, 1, 63, 64, 65, 130, 5009):
        rows = random.integers(0, 256, size, dtype=np.uint64)
        rows[::7] |= np.uint64(1 << 63)
        rules = [(0, 0), (near, 0), (1, 1), (0, near), (1, 0), (1, 0),
                 (0, 1), (3, 4), (1 << 63, 0)]
        ranges = [(0, size), (0, 0), (size, size), (min(size, 63), min(size, 65)), (0, size)]
        requests = [(str(i), l, r, rules) for i, (l, r) in enumerate(ranges)]
        measured = run(rows, requests, 1, methods, db)
        for result in measured:
            scope = rows[result["l"]:result["r"]]
            expected = [np.count_nonzero(((scope & a) == a) & ((scope & b) == 0)) for a, b in rules]
            assert list(map(int, result["results"].split(","))) == expected
            if result["backend"].endswith("_memo") and result["ordinal"] == len(ranges):
                assert result["result_cache_hits"] == len(rules)

    first = [(1, 0), (0, 2)]
    second = [(0, 2), (3, 0), (3, 0), (1, 0)]
    trace = [("first", 1, 5, first), ("partial", 1, 5, second),
             ("repeat", 1, 5, second), ("new_range", 2, 5, second)]
    for method in ("tree_direct_memo", "bitmap_direct_memo", "online_direct_memo", "sql_opt_memo"):
        result = run(np.arange(9, dtype=np.uint64), trace, 1, [method], db)
        assert [r["result_cache_hits"] for r in result] == [0, 2, 4, 0]
        assert [r["result_cache_entries"] for r in result] == [2, 3, 3, 6]
        assert result[1]["results"] == result[2]["results"] == "2,1,1,2"

def check_roaring(db):
    random=np.random.default_rng(92343)
    for n in (0,63,64,65,4097,65535,65536,65537,155063):
        offsets=np.arange(n,dtype=np.uint64)
        rows=random.integers(0,4,n,dtype=np.uint64)
        rows[offsets%3941==7]|=np.uint64(4)
        rows[offsets%65536<4096]|=np.uint64(8)
        rows[offsets%65536<4097]|=np.uint64(16)
        rows[offsets%65536>=4096]|=np.uint64(32)
        rows[offsets%65536>=4096]|=np.uint64(1<<63)
        rules=[(1,0),(0,1),(0,0),(1,1),(6,0),(5,2),(0,3),(0,7),(8,0),
               (16,0),(8,16),(16,8),(0,1<<63),(1<<63,0),(1<<63,32),(3,64)]
        ranges=[(0,n),(min(65535,n),min(65538,n)),(min(4087,n),min(73991,n)),(0,n),(n,n)]
        requests=[(str(i),left,right,rules) for i,(left,right) in enumerate(ranges)]
        measured=run(rows,requests,1,["roaring_direct","roaring_direct_memo","bitmap_direct"],db)
        for record in measured:
            val=rows[record["l"]:record["r"]]
            expected=[np.count_nonzero(((val&a)==a)&((val&b)==0)) for a,b in rules]
            assert list(map(int,record["results"].split(",")))==expected


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--roaring",action="store_true")
    args=parser.parse_args()
    session = connect()
    try:
        check_aggregate(session)
        check_boundaries(session)
        if args.roaring:
            check_roaring(session)
    finally:
        session.close()
    print("Checked shuffled row IDs, rejected invalid IDs, empty input, word boundaries, "
          "high-bit and duplicate predicates, empty slices and result-cache reuse.")
