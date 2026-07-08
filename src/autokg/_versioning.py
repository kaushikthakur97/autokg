from __future__ import annotations

import datetime
import hashlib
import json
from pathlib import Path
from typing import Any, Optional


class VersionManager:
    def __init__(self, store_dir: str):
        self.store_dir = Path(store_dir)
        self.store_dir.mkdir(parents=True, exist_ok=True)
        self._history_file = self.store_dir / "_versions.json"
        self._history = self._load_history()

    def snapshot(
        self,
        triples: list[dict],
        tag: str,
        description: str = "",
        metadata: Optional[dict] = None,
    ) -> str:
        snapshot_path = self.store_dir / f"{tag}.json"
        data = {
            "tag": tag,
            "description": description,
            "created_at": datetime.datetime.utcnow().isoformat() + "Z",
            "metadata": metadata or {},
            "triple_count": len(triples),
            "triples": triples,
        }

        snapshot_path.write_text(json.dumps(data, default=str, indent=2), encoding="utf-8")

        entry = {
            "tag": tag,
            "description": description,
            "created_at": data["created_at"],
            "triple_count": len(triples),
            "checksum": hashlib.sha256(json.dumps(triples, default=str).encode()).hexdigest(),
            "path": str(snapshot_path.relative_to(self.store_dir)),
        }

        self._history["snapshots"].append(entry)
        self._history["latest"] = tag
        self._save_history()

        return tag

    def checkout(self, tag: str) -> list[dict]:
        for snap in self._history["snapshots"]:
            if snap["tag"] == tag:
                path = self.store_dir / snap["path"]
                if path.exists():
                    data = json.loads(path.read_text(encoding="utf-8"))
                    return data.get("triples", [])
        raise KeyError(f"Snapshot '{tag}' not found")

    def diff(self, tag_a: str, tag_b: str) -> dict:
        triples_a = self._as_set(self.checkout(tag_a))
        triples_b = self._as_set(self.checkout(tag_b))

        added = triples_b - triples_a
        removed = triples_a - triples_b
        modified = set()

        for t_a in triples_a:
            for t_b in triples_b:
                if t_a.split(" . ")[0].split(" ")[0] == t_b.split(" . ")[0].split(" ")[0]:
                    if t_a != t_b and t_a not in removed and t_b not in added:
                        modified.add(f"{t_a} → {t_b}")

        return {
            "tag_a": tag_a,
            "tag_b": tag_b,
            "added": len(added),
            "removed": len(removed),
            "modified": len(modified),
            "triples_a": self._get_count(tag_a),
            "triples_b": self._get_count(tag_b),
            "sample_added": list(added)[:10],
            "sample_removed": list(removed)[:10],
        }

    def list_snapshots(self) -> list[dict]:
        return [
            {k: v for k, v in snap.items() if k != "path"}
            for snap in self._history["snapshots"]
        ]

    def latest(self) -> str:
        return self._history.get("latest", "")

    def _as_set(self, triples: list[dict]) -> set[str]:
        result: set[str] = set()
        for t in triples:
            result.add(f"{t.get('subject', '')} {t.get('predicate', '')} {t.get('object', '')} .")
        return result

    def _get_count(self, tag: str) -> int:
        for snap in self._history["snapshots"]:
            if snap["tag"] == tag:
                return snap.get("triple_count", 0)
        return 0

    def _load_history(self) -> dict:
        if self._history_file.exists():
            return json.loads(self._history_file.read_text(encoding="utf-8"))
        return {"snapshots": [], "latest": ""}

    def _save_history(self):
        self._history_file.write_text(json.dumps(self._history, default=str, indent=2), encoding="utf-8")
