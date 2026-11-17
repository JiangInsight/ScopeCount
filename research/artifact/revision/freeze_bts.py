

import argparse, hashlib, io, json, os, zipfile
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent


def freeze(base, dest):
    masks = np.memmap(base / "bts.rows", dtype="<u8", mode="r")
    keys = np.unique(masks)
    assert len(keys) <= 256
    meta = json.loads((base / "bts.json").read_text())
    meta["nullmask_sha256"] = hashlib.sha256(masks).hexdigest()
    with zipfile.ZipFile(
        dest, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6
    ) as z:
        z.writestr("bts.json", json.dumps(meta, indent=2))
        z.write(base / "bts.trace.tsv", "bts.trace.tsv")
        z.writestr("dictionary.u64", keys.astype("<u8").tobytes())
        with z.open("ordered.codes", "w") as out:
            for pos in range(0, len(masks), 100000):
                out.write(
                    np.searchsorted(keys, masks[pos : pos + 100000])
                    .astype("uint8")
                    .tobytes()
                )


def restore(base, dest):
    base.mkdir(exist_ok=True, parents=True)
    with zipfile.ZipFile(dest) as z:
        meta = json.loads(z.read("bts.json"))
        keys = np.frombuffer(z.read("dictionary.u64"), dtype="<u8")
        target = base / "bts.rows"
        if target.exists():
            with target.open("rb") as f:
                assert (
                    hashlib.file_digest(f, "sha256").hexdigest()
                    == meta["nullmask_sha256"]
                )
        else:
            tmp = target.with_suffix(".tmp")
            with z.open("ordered.codes") as src, tmp.open("wb") as out:
                while chunk := src.read(100000):
                    out.write(
                        keys[np.frombuffer(chunk, dtype="uint8")]
                        .astype("<u8")
                        .tobytes()
                    )
            with tmp.open("rb") as f:
                assert (
                    hashlib.file_digest(f, "sha256").hexdigest()
                    == meta["nullmask_sha256"]
                )
            tmp.replace(target)
        assert target.stat().st_size == meta["rows"] * 8
        for name in ("bts.json", "bts.trace.tsv"):
            (base / name).write_bytes(z.read(name))
        print(
            meta["rows"],
            "rows checked",
            len(keys),
            "signatures",
            len(meta["sources"]),
            "archived monthly sources",
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["freeze", "restore"])
    parser.add_argument(
        "--base",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "datasets/bts",
    )
    parser.add_argument("--archive", type=Path, default=HERE / "bts_input.zip")
    a = parser.parse_args()
    (freeze if a.mode == "freeze" else restore)(a.base, a.archive)
