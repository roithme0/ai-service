"""Exclusive, ephemeral image storage."""

import os
import re
import shutil
import stat
from pathlib import Path
from uuid import UUID, uuid4

RUN = re.compile(
    r"^image-generation-run-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)


def is_link(path: Path) -> bool:
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & 0x400
    )


def initialize(root: Path) -> Path:
    if not root.is_absolute():
        raise ValueError("Image storage root must be absolute")
    root.mkdir(parents=True, exist_ok=True)
    if is_link(root) or not root.is_dir():
        raise ValueError("Unsafe image storage root")
    for child in root.iterdir():
        if RUN.fullmatch(child.name) and not is_link(child) and child.is_dir():

            def raise_walk_error(error: OSError) -> None:
                raise error

            for current, dirs, files in os.walk(
                child, followlinks=False, onerror=raise_walk_error
            ):
                if any(is_link(Path(current) / name) for name in dirs + files):
                    raise ValueError("Unsafe image storage entry")
            shutil.rmtree(child)
    run = root / f"image-generation-run-{uuid4()}"
    run.mkdir()
    return run


def publish(run: Path, generation_id: UUID, data: bytes) -> Path:
    partial = run / f"{generation_id}.part"
    final = run / f"{generation_id}.png"
    with partial.open("xb") as stream:
        stream.write(data)
    partial.replace(final)
    return final


def remove(run: Path, generation_id: UUID) -> None:
    for suffix in (".part", ".png"):
        try:
            (run / f"{generation_id}{suffix}").unlink(missing_ok=True)
        except OSError:
            pass
