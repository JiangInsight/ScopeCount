

import os
from pathlib import Path
import platform
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "engine"))
import build_engine as sdk

OUT = Path(
    os.environ.get(
        "SCOPEFUSED_OUTPUT", HERE.parents[2] / "compiled" / "duckdb155_fused"
    )
)


def main():
    cache = sdk.OUT
    if not all(
        (cache / n).is_file()
        for n in ["duckdb.h", "duckdb_extension.h", "append_metadata.py"]
    ):
        subprocess.run(
            [sys.executable, str(HERE.parent / "engine" / "build_engine.py")],
            check=True,
        )
    OUT.mkdir(exist_ok=True, parents=True)
    if os.name == "nt":
        locator = (
            Path(os.environ["ProgramFiles(x86)"])
            / "Microsoft Visual Studio/Installer/vswhere.exe"
        )
        root = subprocess.check_output(
            [
                str(locator),
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
        script = OUT / "build.cmd"
        script.write_text(
            f'@echo off\ncall "{root}/VC/Auxiliary/Build/vcvars64.bat" >nul\nif errorlevel 1 exit /b 1\ncl /nologo /O2 /EHsc /std:c++20 /arch:AVX2 /LD /DNOMINMAX /I"{cache}" "{HERE/"fused.cpp"}" /Fe:scopefused.dll\n'
        )
        subprocess.run(
            [os.environ["COMSPEC"], "/d", "/c", str(script)], cwd=OUT, check=True
        )
        lib, abi = "scopefused.dll", "windows_amd64"
    else:
        import duckdb

        lib, abi = "scopefused.so", duckdb.sql("PRAGMA platform").fetchone()[0]
        flags = (
            ["-mavx2", "-mpopcnt"] if platform.machine() in ("x86_64", "amd64") else []
        )
        subprocess.run(
            [
                os.environ.get("CXX", "c++"),
                "-shared",
                "-fPIC",
                "-O3",
                "-std=c++20",
                *flags,
                "-I",
                str(cache),
                str(HERE / "fused.cpp"),
                "-o",
                lib,
            ],
            cwd=OUT,
            check=True,
        )
    subprocess.run(
        [
            sys.executable,
            str(cache / "append_metadata.py"),
            "-l",
            lib,
            "-n",
            "scopefused",
            "-o",
            "scopefused.duckdb_extension",
            "-p",
            abi,
            "-dv",
            "v1.2.0",
            "-ev",
            "v0.2.0",
            "--abi-type",
            "C_STRUCT",
        ],
        cwd=OUT,
        check=True,
    )
    print(OUT / "scopefused.duckdb_extension")


if __name__ == "__main__":
    main()
