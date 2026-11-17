

from pathlib import Path
import os, sys, subprocess
import pyarrow

h = Path(__file__).resolve().parent
root = h.parents[2]
sdk = root / "compiled" / "duckdb155_final"
out = Path(os.environ.get("SCOPEPAGE_BUILD", root / "compiled" / "scopepages"))
out.mkdir(exist_ok=True)
if not (sdk / "duckdb_extension.h").exists():
    subprocess.run(
        [sys.executable, h.parent / "engine" / "build_engine.py"], check=True
    )
lib = Path(pyarrow.__file__).parent
roar = root / "compiled" / "duckdb155_roaring"
if not (roar / "roaring.h").exists():
    subprocess.run(
        [sys.executable, h.parent / "engine" / "build_engine.py", "--roaring"],
        check=True,
    )
if os.name == "nt":
    loc = (
        Path(os.environ["ProgramFiles(x86)"])
        / "Microsoft Visual Studio/Installer/vswhere.exe"
    )
    vs = subprocess.check_output(
        [
            loc,
            "-latest",
            "-products",
            "*",
            "-requires",
            "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
            "-property",
            "installationPath",
        ],
        text=True,
    ).strip()
    cmd = out / "build.cmd"
    cmd.write_text(
        f'@echo off\ncall "{vs}/VC/Auxiliary/Build/vcvars64.bat" >nul\nif errorlevel 1 exit /b 1\n'
        f'cl /nologo /std:c11 /O2 /MD /DNDEBUG /c /TC "{roar/"roaring.c"}" /Fo:cr.obj\nif errorlevel 1 exit /b 1\n'
        f'cl /nologo /std:c++20 /EHsc /MD /O2 /LD /DNOMINMAX cr.obj /I"{roar}" /I"{sdk}" /I"{pyarrow.get_include()}" "{h/"extension.cpp"}" "{lib/"arrow.lib"}" "{lib/"parquet.lib"}" /Fe:scopepages.dll\n'
    )
    subprocess.run([os.environ["COMSPEC"], "/d", "/c", str(cmd)], cwd=out, check=True)
    dll = "scopepages.dll"
    platform = "windows_amd64"
else:
    import duckdb

    pyarrow.create_library_symlinks()
    dll = "scopepages.so"
    platform = duckdb.sql("PRAGMA platform").fetchone()[0]
    subprocess.run(
        ["cc", "-std=c11", "-O3", "-fPIC", "-c", roar / "roaring.c", "-o", "cr.o"],
        cwd=out,
        check=True,
    )
    subprocess.run(
        [
            "c++",
            "-std=c++20",
            "-O3",
            "-fPIC",
            "-shared",
            "cr.o",
            f"-I{roar}",
            f"-I{sdk}",
            f"-I{pyarrow.get_include()}",
            h / "extension.cpp",
            f"-L{lib}",
            f"-Wl,-rpath,{lib}",
            "-lparquet",
            "-larrow",
            "-o",
            dll,
        ],
        cwd=out,
        check=True,
    )
subprocess.run(
    [
        sys.executable,
        sdk / "append_metadata.py",
        "-l",
        dll,
        "-n",
        "scopepages",
        "-o",
        "scopepages.duckdb_extension",
        "-p",
        platform,
        "-dv",
        "v1.2.0",
        "-ev",
        "v0.1.0",
        "--abi-type",
        "C_STRUCT",
    ],
    cwd=out,
    check=True,
)
