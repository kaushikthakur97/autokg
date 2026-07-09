from __future__ import annotations

import json
import math
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl

from ._v1 import load_v1_config, build_v1


@dataclass
class DistributedBuildReport:
    backend: str
    partitions: int
    partition_files: list[str]
    final_output_dir: str
    duration_seconds: float
    notes: list[str]


class DistributedBuildCoordinator:
    """Local partitioned build coordinator with backend hooks.

    It prepares deterministic table partitions and a distributed manifest. The final
    graph build remains semantically identical to normal v1 output. This is the
    safe default; Ray/Dask/Spark adapters can plug into the same interface later.
    """

    def __init__(self, config_path: str | Path, *, partitions: int = 4, backend: str = "local"):
        self.config_path = Path(config_path)
        self.config = load_v1_config(config_path)
        self.partitions = max(1, partitions)
        self.backend = backend

    def run(self) -> DistributedBuildReport:
        start = time.time()
        workdir = Path(tempfile.mkdtemp(prefix="autokg_distributed_"))
        part_files: list[str] = []
        for table in self.config.get("tables", []):
            src = Path(table["source"])
            if not src.exists() or src.suffix.lower() not in {".csv", ".parquet"}:
                continue
            df = pl.read_csv(src) if src.suffix.lower() == ".csv" else pl.read_parquet(src)
            size = max(1, math.ceil(df.height / self.partitions))
            table_dir = workdir / table["name"]
            table_dir.mkdir(parents=True, exist_ok=True)
            for i in range(self.partitions):
                shard = df.slice(i * size, size)
                if shard.height == 0:
                    continue
                out = table_dir / f"part-{i:05d}.csv"
                shard.write_csv(out)
                part_files.append(str(out))
        final = build_v1(self.config_path)
        report = DistributedBuildReport(
            backend=self.backend,
            partitions=self.partitions,
            partition_files=part_files,
            final_output_dir=final.output_dir,
            duration_seconds=round(time.time() - start, 4),
            notes=["Partition files created for distributed planning.", "Final semantic graph built with v1 deterministic compiler for correctness."],
        )
        out = Path(final.output_dir) / "distributed_report.json"
        out.write_text(json.dumps(report.__dict__, indent=2), encoding="utf-8")
        return report
