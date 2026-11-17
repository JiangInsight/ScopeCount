import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time
import zipfile

ROOT = Path(__file__).resolve().parent
ART = ROOT / 'research' / 'artifact'
OUT = ROOT / 'outputs'
HISTORY = []


def call(script, *args, env=None):
    command = [sys.executable, str(script), *map(str, args)]
    started = time.perf_counter()
    process = subprocess.run(command, cwd=ROOT, env={**os.environ, 'PYTHONUTF8':'1', **(env or {})}, text=True, encoding='utf-8', errors='replace', stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    output = process.stdout.replace(str(ROOT), '.').replace(str(Path(sys.executable).parent), '<python>')
    print(output, end='', flush=True)
    HISTORY.append(dict(command=[str(x).replace(str(ROOT), '.') for x in command[1:]], returncode=process.returncode, elapsed_s=time.perf_counter()-started, output=output))
    if process.returncode:
        raise subprocess.CalledProcessError(process.returncode, command)


def unpack(archive, destination):
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        sums = json.loads(z.read('SHA256.json')) if 'SHA256.json' in names else {}
        for info in z.infolist():
            name = Path(info.filename)
            resolved = (destination / name).resolve()
            if not resolved.is_relative_to(destination.resolve()):
                raise ValueError('Archive member escapes destination')
            if info.is_dir():
                continue
            data = z.read(info)
            expected = sums.get(info.filename)
            if expected and hashlib.sha256(data).hexdigest() != expected:
                raise ValueError('Archive member checksum mismatch: '+info.filename)
            resolved.parent.mkdir(parents=True, exist_ok=True)
            if resolved.exists() and resolved.read_bytes() != data:
                raise ValueError('Existing input differs: '+str(resolved))
            resolved.write_bytes(data)


def native():
    directory = ROOT / 'compiled' / 'native'
    directory.mkdir(parents=True, exist_ok=True)
    sources = [ART / (n+'.cpp') for n in ('runner','bundles','controls','cut','gate','cut_execution','topology','published_run')]
    sources += [ART/'revision/prefix.cpp', ART/'pageaudit/test_pivot.cpp', ART/'pageaudit/test_segments.cpp', ART/'pageaudit/profile_segments.cpp']
    if os.name == 'nt':
        locator = Path(os.environ['ProgramFiles(x86)'])/'Microsoft Visual Studio/Installer/vswhere.exe'
        installation = subprocess.check_output([str(locator), '-latest', '-products', '*', '-requires', 'Microsoft.VisualStudio.Component.VC.Tools.x86.x64', '-property', 'installationPath'], text=True).strip()
        if not installation:
            raise RuntimeError('Install the x64 Visual Studio C++ build tools')
        commands = ['@echo off', f'call "{installation}/VC/Auxiliary/Build/vcvars64.bat" >nul', 'if errorlevel 1 exit /b 1']
        for source in sources:
            commands += [f'cl /nologo /O2 /EHsc /std:c++20 /DNOMINMAX "{source}" /Fe:"{source.stem}.exe"', 'if errorlevel 1 exit /b 1']
        script = directory/'build.cmd'
        script.write_text('\n'.join(commands)+'\n')
        subprocess.run([os.environ['COMSPEC'],'/d','/c',str(script)],cwd=directory,check=True)
    else:
        for source in sources:
            subprocess.run([os.environ.get('CXX','c++'),'-O3','-std=c++20',str(source),'-o',str(directory/source.stem)],check=True)
    for source in sources:
        name = source.stem + ('.exe' if os.name == 'nt' else '')
        shutil.copy2(directory/name, ROOT/'compiled'/name)
    HISTORY.append(dict(command=['native-build'],returncode=0,sources=[str(x.relative_to(ROOT)) for x in sources],programs=[x.stem for x in sources]))


def build():
    call(ART/'engine/build_engine.py')
    call(ART/'engine/build_engine.py','--roaring')
    call(ART/'fused/build.py')
    call(ART/'pageaudit/build.py')
    native()


def restore():
    for name in ('data','runs','scales','compiled','research/figures'):
        (ROOT/name).mkdir(parents=True,exist_ok=True)
    call(ART/'reproduce.py','restore')
    call(ART/'workload.py',*[ROOT/'data'/(name+'.npz') for name in ('crash','diabetes','maude','nhanes','scania','storm','survey','taxi')])
    call(ART/'operational/freeze_traces.py','restore','--root',ROOT/'traces')
    call(ART/'operational/verify_traces.py','--root',ROOT/'traces')
    unpack(ART/'operational/grouped_fcc.zip',ROOT/'datasets/fcc')
    unpack(ART/'operational/matched_traces.zip',ROOT/'traces')
    unpack(ART/'operational/scoped_sqlshare.zip',ROOT/'datasets/scoped_sqlshare')
    unpack(ART/'sqlshare_groups/evidence.zip',ROOT/'datasets/sqlshare')
    (ROOT/'datasets/stops/panels').mkdir(parents=True,exist_ok=True)


def verify():
    for name in ('fused/verify.py','fused/verify_cover.py','fused/forest_verify.py','pageaudit/check_width.py','pageaudit/check.py','pageaudit/check_partial.py','engine/verify_engine.py'):
        call(ART/name)
    call(ART/'engine/verify_engine.py','--roaring',env={'SCOPECNT_EXTENSION':str(ROOT/'compiled/duckdb155_roaring/scopecount.duckdb_extension')})
    for name in ('test_pivot','test_segments'):
        program=ROOT/'compiled/native'/(name+('.exe' if os.name=='nt' else ''))
        process=subprocess.run([str(program)],capture_output=True,text=True)
        print(process.stdout,flush=True)
        HISTORY.append(dict(command=[str(program.relative_to(ROOT))],returncode=process.returncode,output=process.stdout+process.stderr))
        process.check_returncode()
    call(ART/'revision/recompilation_witness.py')
    call(ART/'revision/base_admission.py')
    call(ART/'revision/verify_release.py')


def benchmark(suite, output, repeats, limit):
    output.mkdir(parents=True,exist_ok=True)
    if suite in ('sqlshare','all'):
        call(ART/'sqlshare_groups/benchmark.py','--data',ROOT/'datasets/sqlshare/data','--out',output/'sqlshare-resident','--repeats',5*((repeats+4)//5))
        call(ART/'sqlshare_groups/benchmark.py','--file-replay','--data',ROOT/'datasets/sqlshare/data','--out',output/'sqlshare-file','--repeats',5*((repeats+4)//5),'--methods','sql','metadata_star','dense','roaring','endpoint')
    if suite in ('fcc','all'):
        call(ART/'fused/fcc.py','--base',ROOT/'datasets/fcc','--out',output/'fcc','--reps',4*((repeats+3)//4),'--layouts','original','shuffled')
    if suite in ('file','all'):
        call(ART/'pageaudit/benchmark.py','--fcc',ROOT/'datasets/fcc','--stops',ROOT/'datasets/stops/panels','--out',output/'file','--repeats',5*((repeats+4)//5),'--methods','sql','dense','roaring','packed','endpoint')
    if suite in ('stops','all') and list((ROOT/'datasets/stops/panels').glob('*/case.json')):
        names=[p.parent.name for p in sorted((ROOT/'datasets/stops/panels').glob('*/case.json'))]
        call(ART/'livegroups/bench.py','--cache',ROOT/'datasets/stops','--extension',ROOT/'compiled/duckdb155_fused/scopefused.duckdb_extension','--out',output/'stops-resident','--reps',10*((repeats+9)//10),*names)
        call(ART/'pageaudit/degree.py','--cache',ROOT/'datasets/stops','--fcc',ROOT/'datasets/fcc','--out',output/'stops-degree/trials.tsv','--repeats',repeats)
    if suite in ('retained','all'):
        for corpus in ('transport','ci'):
            call(ROOT/'experiments/replay_subset.py','--corpus',corpus,'--limit',limit,'--repeats',repeats,'--out',output/corpus)
    if suite in ('controls','all'):
        call(ART/'fused/controls.py','--out',output/'controls','--reps',7*((repeats+6)//7))
        call(ART/'pageaudit/segment_controls.py','--out',output/'segment-controls/trials.tsv')


def main():
    sys.stdout.reconfigure(encoding='utf-8',errors='replace')
    parser=argparse.ArgumentParser()
    parser.add_argument('stage',choices=['build','restore','verify','quick','benchmark','fetch','summarize'])
    parser.add_argument('--suite',choices=['all','sqlshare','fcc','file','stops','retained','controls'],default='all')
    parser.add_argument('--out',type=Path,default=OUT/'validation')
    parser.add_argument('--repeats',type=int,default=5)
    parser.add_argument('--limit',type=int,default=8)
    parser.add_argument('--names',nargs='*',default=['ca_bakersfield'])
    parser.add_argument('--rscript')
    parser.add_argument('--all-sources',action='store_true')
    parser.add_argument('--frozen',action='store_true')
    args=parser.parse_args()
    args.out.mkdir(parents=True,exist_ok=True)
    try:
        if args.stage=='build':build()
        elif args.stage=='restore':restore()
        elif args.stage=='verify':verify()
        elif args.stage=='quick':
            restore()
            verify()
            benchmark('sqlshare',args.out,5,args.limit)
            benchmark('fcc',args.out,4,args.limit)
            benchmark('file',args.out,5,args.limit)
            benchmark('stops',args.out,5,args.limit)
            benchmark('retained',args.out,1,args.limit)
            call(ROOT/'experiments/summarize.py','--root',args.out,'--out',args.out/'summary')
        elif args.stage=='benchmark':benchmark(args.suite,args.out,args.repeats,args.limit)
        elif args.stage=='fetch':
            if args.rscript:
                call(ART/'livegroups/stops.py','--cache',ROOT/'datasets/stops','--rscript',args.rscript,*([] if args.all_sources else args.names))
            else:call(ROOT/'experiments/fetch_stops.py','--cache',ROOT/'datasets/stops',*(['--all'] if args.all_sources else args.names))
        elif args.stage=='summarize':
            call(ROOT/'experiments/summarize.py','--root',args.out,'--out',args.out/'summary',*(['--frozen'] if args.frozen else []))
            if args.frozen:
                call(ART/'revision/verify_release.py')
                call(ART/'revision/ci_payback.py','--packed',ART/'revision/evidence','--tex',args.out/'summary/observed-payback.tex','--json',args.out/'summary/observed-payback.json')
    finally:
        versions={}
        for name in ('duckdb','pyarrow','numpy','pandas'):
            module=__import__(name)
            versions[name]=module.__version__
        record=dict(stage=args.stage,platform=platform.platform(),python=platform.python_version(),versions=versions,performance_claim=False if args.stage in ('quick','verify') else None,commands=HISTORY)
        (args.out/('run-'+args.stage+'.json')).write_text(json.dumps(record,indent=2)+'\n')


if __name__=='__main__':
    main()
