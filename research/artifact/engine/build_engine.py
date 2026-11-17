
import hashlib
import argparse
import io
import os
import pathlib
import platform
import subprocess
import sys
import urllib.request
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
OUT = pathlib.Path(os.environ.get("SCOPECNT_BUILD_DIR", HERE.parents[2] / "compiled" / "duckdb155_final"))
SDK = "https://github.com/duckdb/duckdb/releases/download/v1.5.5/libduckdb-windows-amd64.zip"
METADATA = "https://raw.githubusercontent.com/duckdb/extension-ci-tools/2e5d22fa1b1c42e6fc7aa84a8e66a15e6b492b30/scripts/append_extension_metadata.py"
SDK_SHA256 = "8375eb1fcf2212e8a0817950354815d4dde9dd383c2d9fa7b8975b71e278c1bd"
METADATA_SHA256 = "4613b2b5b284a2820927508375078cd433f6ed6c7a2ad832dbc6278d35ae21fa"
ROARING_RELEASE = "https://github.com/RoaringBitmap/CRoaring/releases/download/v5.5.5/"
ROARING_FILES = {
    "roaring.c": "190216f349ac5aad430b58ed9b9d5b1966a2462a14ce045b0ca59d8507a9cee8",
    "roaring.h": "1a336307c3b5a732045941d1bd33232aa4b45661366ac9643c583e6d67513a34",
}


def fetch(url, expected):
    with urllib.request.urlopen(url, timeout=120) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != expected:
        raise RuntimeError("upstream checksum mismatch: " + url)
    return data


def compile_windows(roaring):
    setup = ""
    if "VSCMD_VER" not in os.environ:
        locator = pathlib.Path(os.environ["ProgramFiles(x86)"]) / "Microsoft Visual Studio/Installer/vswhere.exe"
        install = subprocess.check_output(
            [str(locator), "-latest", "-products", "*", "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64",
             "-property", "installationPath"], text=True
        ).strip()
        if not install:
            raise RuntimeError("Run from the x64 Visual Studio Developer Command Prompt or install the C++ build tools.")
        vcvars = pathlib.Path(install) / "VC/Auxiliary/Build/vcvars64.bat"
        setup = f'call "{vcvars}" >nul\nif errorlevel 1 exit /b 1\n'
    command = OUT / "compile_scope.cmd"
    native = 'cl /nologo /std:c11 /O2 /DNDEBUG /c /TC roaring.c /Fo:croaring.obj\nif errorlevel 1 exit /b 1\n' if roaring else ''
    linked = '/DSCOPECOUNT_ROARING croaring.obj ' if roaring else ''
    command.write_text(
        '@echo off\n' + setup + native + f'cl /nologo /std:c++20 /EHsc /O2 /LD /DNOMINMAX ' + linked +
        f'/I"{OUT}" "{HERE / "scopecount.cpp"}" /Fe:scopecount.dll\n'
    )
    subprocess.run([os.environ["COMSPEC"], "/d", "/c", str(command)], cwd=OUT, check=True)
    return "scopecount.dll", "windows_amd64"


def main():
    global OUT
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--roaring",action="store_true",help="build the additional pinned compressed-bitmap backend")
    args = parser.parse_args()
    if args.roaring and "SCOPECNT_BUILD_DIR" not in os.environ:
        OUT = HERE.parents[2] / "compiled" / "duckdb155_roaring"
    OUT.mkdir(parents=True, exist_ok=True)
    if args.roaring:
        license_data=(HERE/"CRoaring-LICENSE").read_bytes().replace(b"\r\n",b"\n")
        if hashlib.sha256(license_data).hexdigest()!="f8e1f16a3f22e001b44ae9b12625420b9a0c4dbb7ec0e9f83b6a3d38a9525411":
            raise RuntimeError("CRoaring license checksum mismatch")
        (OUT/"CRoaring-LICENSE").write_bytes(license_data)
        for name,digest in ROARING_FILES.items():
            target=OUT/name
            if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest()!=digest:
                target.write_bytes(fetch(ROARING_RELEASE+name,digest))
    if any(not (OUT / fn).exists() for fn in ("duckdb.h", "duckdb_extension.h")):
        with zipfile.ZipFile(io.BytesIO(fetch(SDK, SDK_SHA256))) as archive:
            for fn in ("duckdb.h", "duckdb_extension.h"):
                (OUT / fn).write_bytes(archive.read(fn))
    metadata = OUT / "append_metadata.py"
    if not metadata.exists() or hashlib.sha256(metadata.read_bytes()).hexdigest() != METADATA_SHA256:
        metadata.write_bytes(fetch(METADATA, METADATA_SHA256))
    if os.name == "nt":
        library, abi_platform = compile_windows(args.roaring)
    elif sys.platform == "linux" and platform.machine() in ("x86_64", "aarch64"):
        import duckdb

        library = "scopecount.so"
        abi_platform = duckdb.sql("PRAGMA platform").fetchone()[0]
        flags = []
        if args.roaring:
            subprocess.run([os.environ.get("CC","cc"),"-std=c11","-O3","-fPIC","-DNDEBUG",
                            "-c","roaring.c","-o","croaring.o"],cwd=OUT,check=True)
            flags = ["-DSCOPECOUNT_ROARING","croaring.o"]
        subprocess.run([os.environ.get("CXX", "c++"), "-std=c++20", "-O3", "-DNDEBUG", "-shared", "-fPIC",
                        "-I", str(OUT), str(HERE / "scopecount.cpp"), *flags, "-o", library], cwd=OUT, check=True)
    else:
        raise RuntimeError("This build script supports 64-bit Windows and Linux.")
    subprocess.run([sys.executable, str(metadata), "-l", library, "-n", "scopecount",
                    "-o", "scopecount.duckdb_extension", "-p", abi_platform, "-dv", "v1.2.0",
                    "-ev", "v0.1.0", "--abi-type", "C_STRUCT"], cwd=OUT, check=True)
    print(OUT / "scopecount.duckdb_extension")


if __name__ == "__main__":
    main()
