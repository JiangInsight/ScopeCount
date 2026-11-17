
import argparse
import hashlib
import io
import json
import zipfile
from pathlib import Path, PurePosixPath
import pandas as pd
from pan import BASE as PAN

ARTIFACT=Path(__file__).resolve().parent/"operational_traces.zip"
def digest(b):return hashlib.sha256(b).hexdigest()
def paths(root):
    out={}
    pan=root/"transport";ci=root/"ci"
    for sub,names in [(pan,['datasets.json','manifest.tsv']),(ci,['runs.json','artifacts.json','inputs.tsv','manifest.tsv','coverage.tsv'])]:
        for name in names:
            p=sub/name;out[p.relative_to(root).as_posix()]=p
    for p in (ci/'projected').glob('*.tsv.gz'):out[p.relative_to(root).as_posix()]=p
    for sub in [pan,ci]:
        m=pd.read_csv(sub/'manifest.tsv',sep='\t')
        for row in m[m.status=='ok'].itertuples():
            prefix=Path(row.prefix)
            for suffix in ['.rows','.tsv']+(['.provenance.tsv'] if sub==ci else []):
                p=prefix.with_suffix(suffix);out[p.relative_to(root).as_posix()]=p
    return out

def freeze(root,archive):
    pathmap=paths(root);sums={}
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=8) as z:
        sources=sorted(pathmap.items())
        for arc,p in sources:
            data=p.read_bytes()
            if arc in ['transport/manifest.tsv','ci/manifest.tsv','ci/inputs.tsv']:
                frame=pd.read_csv(io.BytesIO(data),sep='\t',dtype=str,keep_default_na=False)
                frame['prefix']=[Path(x).relative_to(root).as_posix() if x else '' for x in frame.prefix]
                data=frame.to_csv(sep='\t',index=False,lineterminator='\n').encode()
            sums[arc]=digest(data)
            z.writestr(arc,data)
        z.writestr('_sha256.json',json.dumps(sums,sort_keys=True))
    print(len(sums),archive.stat().st_size,digest(archive.read_bytes()))

def restore(root,archive):
    with zipfile.ZipFile(archive) as z:
        sums=json.loads(z.read('_sha256.json'))
        for arc,h in sums.items():
            k=PurePosixPath(arc)
            if k.is_absolute() or '..' in k.parts or k.parts[0] not in ('transport','ci'):raise ValueError(arc)
            data=z.read(arc)
            if digest(data)!=h:raise ValueError(arc)
            if arc in ['transport/manifest.tsv','ci/manifest.tsv','ci/inputs.tsv']:
                frame=pd.read_csv(io.BytesIO(data),sep='\t',dtype=str,keep_default_na=False)
                frame['prefix']=[str(root/Path(x)) if x else '' for x in frame.prefix]
                data=frame.to_csv(sep='\t',index=False,lineterminator='\n').encode()
            p=root/Path(arc);p.parent.mkdir(exist_ok=True,parents=True)
            if p.exists() and p.read_bytes()!=data:
                raise ValueError(f"Use a fresh destination to avoid overwriting {p}")
            p.write_bytes(data)
    print(f"Verified {len(sums)} files")

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('stage',choices=['freeze','restore'])
    parser.add_argument('--root',type=Path,default=PAN.parent);parser.add_argument('--archive',type=Path,default=ARTIFACT)
    a=parser.parse_args();(freeze if a.stage=='freeze' else restore)(a.root.resolve(),a.archive.resolve())
