from pathlib import Path
import pandas as pd
O=Path(__file__).resolve().parents[1];P=O.parent;rows=[];allrat=[];wins=0
for f in sorted((P/'runs').glob('*.control.tsv')):
    ds=f.stem.split('.')[0];s=pd.read_csv(f,sep='\t')
    assert len(s)==189 and s.groupby('bundle').digest.nunique().max()==1
    ref=pd.read_csv(P/'runs'/f'{ds}.joint.tsv',sep='\t').query('width==8').groupby('bundle').digest.first()
    assert (ref.astype(str)==s.groupby('bundle').digest.first().astype(str)).all()
    s['t']=s.compile_ns+s.exec_ns;t=s.groupby(['method','bundle']).t.median().groupby('method').sum()
    allrat.append(t.flat_scalar/t.frontier_joint);wins+=int(t.frontier_joint<t.shared_word_scan)
assert len(allrat)==8
(O/'control_results.tex').write_text(
r"""As a check on the cost of merging scalar plans, we replaced its ordered map with arrays indexed by physical node and a list of touched positions. This separate native trial rotates method order, includes its own joint-frontier control and checks every digest against the main trial. The scalar-to-joint time ratio ranges from %.2f to %.2f across sources. A second control compiles a trie of common literal prefixes and intersects validity words directly within each slice, sharing intermediate words across predicates. The joint frontier is faster than this direct shared word scan on %d of the eight sources; NHANES and Survey favor the scan. Both native controls bypass SQL dispatch. Their timings isolate the cost of sharing within the two native representations."""%(min(allrat),max(allrat),wins),encoding='utf8')
