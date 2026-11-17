from pathlib import Path
import pandas as pd
P=Path(__file__).resolve().parents[2]
f=pd.read_csv(P/'runs'/'batched_sql.tsv',sep='\t');assert len(f)==24 and not f[['dataset','rep']].duplicated().any()
ratio=[];wins=0
for ds,x in f.groupby('dataset'):
    q=pd.read_csv(P/'runs'/(ds+'.sql.tsv'),sep='\t').query("bundle=='1103-complete-0-0'")
    a=(q.prepare_ns+q.exec_ns).median();b=(x.prepare_ns+x.exec_ns).median();ratio.append(a/b);wins+=b<a
(Path(__file__).resolve().parents[1]/'sql_batch_result.tex').write_text(
r"""One SQL statement per slice can charge dispatch many times. As a separate engine control, we placed the 24 endpoint pairs in a relation and used one range join and conditional aggregation grouped by interval identifier. The test uses the first eight complete-case checks of the first seed on each source; all 192 counts per source agree with direct evaluation. The single-statement time was lower on %d of eight sources, with the separate-to-batched time ratio ranging from %.2f to %.2f. Overlapping intervals can produce many intermediate row--interval pairs, so removing dispatch need not improve the engine plan. Neither SQL comparison isolates the cost of a native rank operation."""%(wins,min(ratio),max(ratio)),encoding='utf8')
print(wins,ratio)
