
import struct,tempfile
from pathlib import Path
from reproduce import prog
with tempfile.TemporaryDirectory() as scratch:
 p=Path(scratch)/'test';rows=[0,1,2,3,4,7,1<<62,0,3,2]*10
 p.with_suffix('.rows').write_bytes(struct.pack('<'+'Q'*len(rows),*rows))
 rules=[(0,0),(1,1),(0,1),(1,0),(3,0),(1<<62,0),(0,1<<62),(9,6)]
 slices=[(0,0),(0,1),(64,64),(63,65),(64,100),(0,100)]
 p.with_suffix('.queries').write_text(''.join(f'q{i} {a} {b} {l} {r}\n' for i,(a,b) in enumerate(rules) for l,r in slices))
 prog('bundles',p,p.parent/'bundle.tsv');prog('runner',p,p.parent/'scalar.tsv',1);prog('cut','--self-test')
