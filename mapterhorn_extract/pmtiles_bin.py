from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .extract import Job


class PmtilesNotFound(RuntimeError):
    pass


def find_pmtiles(binary: str | None = None) -> str:
    wanted = binary or "pmtiles"
    found = shutil.which(wanted)
    if found is None:
        raise PmtilesNotFound(
            f"pmtiles binary not found: {wanted}. Install go-pmtiles or give the path to the binary."
        )
    return found


def extract_command(binary: str, job: Job, output: Path, threads: int) -> list[str]:
    command = [
        binary,
        "extract",
        job.url,
        str(output),
        f"--minzoom={job.minzoom}",
        f"--maxzoom={job.maxzoom}",
        f"--download-threads={threads}",
    ]
    if job.region is not None:
        command.append(f"--region={job.region}")
    else:
        command.append("--bbox=" + ",".join(str(c) for c in job.bbox))
    return command


def merge_command(binary: str, inputs: list[Path], output: Path) -> list[str]:
    return [binary, "merge", *(str(path) for path in inputs), str(output)]
