import hashlib
import os
from pathlib import Path
import subprocess
import sys
from urllib.request import urlopen

import duckdb
import pyarrow

root = Path(__file__).resolve().parent
build = root / "build"
sdk = build / "deps"
sdk.mkdir(parents=True,exist_ok=True)
headers = "https://raw.githubusercontent.com/duckdb/duckdb/v1.5.5/src/include/"
roaring = "https://github.com/RoaringBitmap/CRoaring/releases/download/v5.5.5/"
metadata = "https://raw.githubusercontent.com/duckdb/extension-ci-tools/2e5d22fa1b1c42e6fc7aa84a8e66a15e6b492b30/scripts/append_extension_metadata.py"
files = {
    "duckdb.h": (headers+"duckdb.h","48e716b9ce96ca8fead9cb35693fdc0343ac0fc1f6e7db5561fa0f44b674153d"),
    "duckdb_extension.h": (headers+"duckdb_extension.h","a932d6f328c3700dc9dc90ab16a1fd9f76950ea2a1d4cc555cdd33990a7e3dd3"),
    "roaring.c": (roaring+"roaring.c","190216f349ac5aad430b58ed9b9d5b1966a2462a14ce045b0ca59d8507a9cee8"),
    "roaring.h": (roaring+"roaring.h","1a336307c3b5a732045941d1bd33232aa4b45661366ac9643c583e6d67513a34"),
    "append_metadata.py": (metadata,"4613b2b5b284a2820927508375078cd433f6ed6c7a2ad832dbc6278d35ae21fa"),
}
for name,(address,sha) in files.items():
    destination = sdk/name
    if destination.exists() and hashlib.sha256(destination.read_bytes()).hexdigest() == sha:
        continue
    with urlopen(address,timeout=90) as response:
        content = response.read()
    if hashlib.sha256(content).hexdigest() != sha:
        raise ValueError(f"Dependency checksum mismatch: {name}")
    destination.write_bytes(content)

if os.name != "nt":
    raise SystemExit("This build targets 64-bit Windows and the MSVC C++ toolchain.")
if (duckdb.__version__,pyarrow.__version__) != ("1.5.5","24.0.0"):
    raise SystemExit("Install the versions listed in requirements.txt.")
lib = Path(pyarrow.__file__).parent
source = root/"src"
locator = Path(os.environ["ProgramFiles(x86)"])/"Microsoft Visual Studio/Installer/vswhere.exe"
installation = subprocess.check_output([locator,"-latest","-products","*","-requires",
    "Microsoft.VisualStudio.Component.VC.Tools.x86.x64","-property","installationPath"],text=True).strip()
if not installation:
    raise SystemExit("MSVC Build Tools for x64 are required.")
commands = [
    f'call "{installation}/VC/Auxiliary/Build/vcvars64.bat" >nul',
    f'cl /nologo /O2 /std:c11 /MD /DNDEBUG /c /TC "{sdk/"roaring.c"}" /Fo:roaring.obj',
    f'cl /nologo /O2 /std:c++20 /EHsc /MD /DNOMINMAX /LD roaring.obj /I"{sdk}" /I"{pyarrow.get_include()}" "{source/"extension.cpp"}" "{lib/"arrow.lib"}" "{lib/"parquet.lib"}" /Fe:scopepages.dll',
    f'cl /nologo /O2 /std:c++20 /EHsc "{source/"test_pivot.cpp"}" /Fe:test_pivot.exe',
    f'cl /nologo /O2 /std:c++20 /EHsc "{source/"test_segments.cpp"}" /Fe:test_segments.exe',
]
script = build/"compile.cmd"
script.write_text("@echo off\n" + "\nif errorlevel 1 exit /b 1\n".join(commands)
                  + "\nexit /b %errorlevel%\n")
subprocess.run([os.environ["COMSPEC"],"/d","/c","compile.cmd"],cwd=build,check=True)
subprocess.run([sys.executable,sdk/"append_metadata.py","-l","scopepages.dll","-n","scopepages",
                "-o","scopepages.duckdb_extension","-p","windows_amd64","-dv","v1.2.0",
                "-ev","v0.1.0","--abi-type","C_STRUCT"],cwd=build,check=True)
