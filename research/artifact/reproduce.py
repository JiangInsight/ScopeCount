
import argparse,hashlib,os,subprocess,sys,zipfile,json
from pathlib import Path
O=Path(__file__).resolve().parents[1];P=O.parent;A=O/'artifact';D=P/'data';R=P/'runs';C=P/'compiled';S=P/'scales'
names=['crash','diabetes','maude','nhanes','scania','storm','survey','taxi']
def call(*cmd):subprocess.run(list(map(str,cmd)),cwd=O,check=True)
def py(name,*args):call(sys.executable,'-X','utf8',A/(name+'.py'),*args)
def prog(name,*args):call(C/(name+('.exe' if os.name=='nt' else '')),*args)
def restore():
    with zipfile.ZipFile(A/'evidence.zip') as z:
        sums=json.loads(z.read('MANIFEST.json'))
        for k,h in sums.items():
            sub=Path(k);assert not sub.is_absolute() and (len(sub.parts)==2 or k in ('data/published_mcq/natural.rows','data/published_mcq/natural.queries')) and sub.parts[0] in ('data','runs') and '..' not in sub.parts
            data=z.read(k);assert hashlib.sha256(data).hexdigest()==h
            target=P/sub;target.parent.mkdir(exist_ok=True,parents=True)
            if target.exists():
                if hashlib.sha256(target.read_bytes()).hexdigest()!=h:raise SystemExit(f'Existing file differs: {target}. Use a fresh checkout directory to restore the frozen experiment.')
            else:target.write_bytes(data)
        print(f'{len(sums)} archived files verified')
def canonical_rows():py('workload',*[D/(n+'.npz') for n in names])
def tables():
    canonical_rows()
    for f in ['case_tables','report','cut_tables','cut_execution_tables','gate_tables','topology_tables','control_report','sql_report','deployment']:py(f)
    py("published_rules","--frozen-tables")
def build():
    C.mkdir(exist_ok=True)
    sources=['runner','bundles','controls','cut','gate','cut_execution','topology','published_run']
    if os.name=='nt':
        call(os.environ.get('COMSPEC','cmd.exe'),'/d','/c',A/'build_all.cmd')
    else:
        for name in sources:call(os.getenv('CXX','c++'),'-O3','-march=native','-std=c++20',A/(name+'.cpp'),'-o',C/name)
def bench():
    for f in [D,R,C,S]:f.mkdir(exist_ok=True)
    if not all((D/(n+'.npz')).exists() for n in names):raise SystemExit('Restore the archived inputs or run prepare.py before timing.')
    canonical_rows();py('cases');py('extensions')
    for n in names:
        prog('runner',D/n,R/(n+'.single.tsv'),3);prog('bundles',D/n,R/(n+'.joint.tsv'));prog('controls',D/n,R/(n+'.control.tsv'))
    for n in ['maude','nhanes','storm','survey']:prog('bundles',D/(n+'_case'),R/(n+'_case.joint.tsv'))
    for f in sorted(S.glob('*.rows')):prog('bundles',f.with_suffix(''),R/(f.stem+'.ext.tsv'))
    for bin,out in [('cut','cut'),('gate','gate'),('cut_execution','cut_execution'),('topology','topology')]:prog(bin,R/(out+'.tsv'),*[D/n for n in names])
    if (D/'published_mcq'/'natural.rows').exists():prog('published_run',D/'published_mcq'/'natural',R/'publisher_times.tsv')
    else:py('published_rules','--binary',C/('published_run.exe' if os.name=='nt' else 'published_run'))
    py('sql_control',*[D/(n+'.npz') for n in names]);py('sql_batch');tables()
if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('stage',choices=['restore','tables','build','run']);args=ap.parse_args()
    {'restore':restore,'tables':tables,'build':build,'run':bench}[args.stage]()
