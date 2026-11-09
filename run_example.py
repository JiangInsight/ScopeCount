import csv
from pathlib import Path
import subprocess
import tempfile

import duckdb
import pyarrow as pa
import pyarrow.parquet as pq

root = Path(__file__).resolve().parent
with (root/"data/audit.csv").open(newline="") as stream:
    rows = list(csv.DictReader(stream))
columns = {key:pa.array([int(r[key]) if r[key] else None for r in rows],type=pa.int32())
           for key in ("group","field_a","field_b")}
query = "SELECT unnest(scope_page_counts(content, 0, '2/0,4/0', ?, ?, ?)) FROM read_blob(?)"
with tempfile.TemporaryDirectory() as tmp, duckdb.connect(config={"allow_unsigned_extensions":"true","threads":"1"}) as db:
    file = Path(tmp)/"audit.parquet"
    pq.write_table(pa.table(columns),file,row_group_size=9)
    extension = (root/"build/scopepages.duckdb_extension").as_posix().replace("'","''")
    db.execute(f"LOAD '{extension}'")
    for start,end in [(0,len(rows)),(2,12),(8,10),(4,4)]:
        sql = """SELECT "group", count(*), count(*) - count(field_a) + count(*) - count(field_b)
                 FROM read_parquet(?, file_row_number=true)
                 WHERE file_row_number >= ? AND file_row_number < ? GROUP BY "group" ORDER BY "group" """
        expected = db.execute(sql,[str(file),start,end]).fetchall()
        for mode in ("endpoint","segment","segment_one","dense","roaring","packed"):
            result = db.execute(query,[start,end,mode,str(file)]).fetchall()
            actual = sorted(tuple(v[:3]) for v, in result)
            if actual != expected:
                raise ValueError((start,end,mode,actual,expected))
for program in ("test_pivot.exe","test_segments.exe"):
    subprocess.run([root/"build"/program],check=True)
print("All six physical plans agree with grouped SQL on four intervals.")
