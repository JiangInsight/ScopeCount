
from pathlib import Path
import hashlib,json,zipfile,tempfile,os
P=Path(__file__).resolve().parents[2];A=Path(__file__).resolve().parent
datasets=['crash','diabetes','maude','nhanes','scania','storm','survey','taxi']
files=[P/'data'/(d+ext) for d in datasets for ext in ('.npz','.json')]
files += [P/'data'/'published_mcq'/('natural.'+ext) for ext in ('rows','queries')]
files+=sorted((P/'runs').glob('*.tsv'))
for f in files:
 if not f.exists() or f.stat().st_size<10:raise ValueError(f)
with zipfile.ZipFile(A/'evidence.zip','w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as z:
 sums={}
 def add(key,data):
    info=zipfile.ZipInfo(key,(2026,11,9,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
    z.writestr(info,data)
 for f in files:
    k=f.relative_to(P).as_posix();data=f.read_bytes();sums[k]=hashlib.sha256(data).hexdigest();add(k,data)
 add('MANIFEST.json',json.dumps(sums,indent=2,sort_keys=True).encode())
print(f'{len(sums)} archived files; {(A/"evidence.zip").stat().st_size:,} bytes')
