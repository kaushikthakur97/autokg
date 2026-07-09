from __future__ import annotations

import datetime
from datetime import timezone
import os
import platform
import uuid
from typing import Optional

from ._types import PROV, DCTERMS


class ProvenanceTracker:
    def __init__(self, namespace: str, pipeline_name: str = "autokg-pipeline"):
        self.namespace = namespace.rstrip("/#")
        self.pipeline_name = pipeline_name
        self._run_id = str(uuid.uuid4())
        self._run_started = datetime.datetime.now(tz=timezone.utc)
        self._run_iri = f"{self.namespace}/pipeline/run/{self._run_id}"
        self._agent_iri = f"{self.namespace}/agent/{platform.node() or 'autokg-worker'}"
        self._activities: list[dict] = []
        self._entities: list[dict] = []

    def record_source(
        self,
        source_path: str,
        source_format: str = "parquet",
        entity_type: Optional[str] = None,
        row_count: int = 0,
    ) -> str:
        source_id = str(uuid.uuid4())
        entity_iri = f"{self.namespace}/dataset/{source_id}"
        self._entities.append({
            "iri": entity_iri,
            "source_path": source_path,
            "format": source_format,
            "entity_type": entity_type,
            "row_count": row_count,
        })
        return entity_iri

    def record_activity(
        self,
        activity_type: str,
        description: str = "",
        used_entities: Optional[list[str]] = None,
        generated_entities: Optional[list[str]] = None,
    ) -> str:
        activity_id = str(uuid.uuid4())
        activity_iri = f"{self.namespace}/activity/{activity_id}"
        self._activities.append({
            "iri": activity_iri,
            "type": activity_type,
            "description": description,
            "used": used_entities or [],
            "generated": generated_entities or [],
            "timestamp": datetime.datetime.now(tz=timezone.utc).isoformat(),
        })
        return activity_iri

    def generate_triples(self) -> list[dict]:
        triples: list[dict] = []
        ri = self._run_iri
        ai = self._agent_iri

        triples.append({"subject": ri, "predicate": "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", "is_iri": True, "object": f"{PROV}Activity"})
        triples.append({"subject": ri, "predicate": f"{PROV}startedAtTime", "object": self._run_started.isoformat().replace("+00:00", "Z"), "datatype": "http://www.w3.org/2001/XMLSchema#dateTime"})
        triples.append({"subject": ri, "predicate": f"{PROV}wasAssociatedWith", "is_iri": True, "object": ai})

        triples.append({"subject": ai, "predicate": "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", "is_iri": True, "object": f"{PROV}Agent"})
        triples.append({"subject": ai, "predicate": "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", "is_iri": True, "object": f"{PROV}SoftwareAgent"})

        for entity in self._entities:
            ei = entity["iri"]
            triples.append({"subject": ei, "predicate": "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", "is_iri": True, "object": f"{PROV}Entity"})
            if entity.get("source_path"):
                triples.append({"subject": ei, "predicate": f"{DCTERMS}source", "object": entity["source_path"], "datatype": "http://www.w3.org/2001/XMLSchema#string"})
            triples.append({"subject": ri, "predicate": f"{PROV}used", "is_iri": True, "object": ei})

        for activity in self._activities:
            ai_iri = activity["iri"]
            triples.append({"subject": ai_iri, "predicate": "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", "is_iri": True, "object": f"{PROV}Activity"})
            triples.append({"subject": ri, "predicate": f"{PROV}wasInformedBy", "is_iri": True, "object": ai_iri})

            for used_e in activity.get("used", []):
                triples.append({"subject": ai_iri, "predicate": f"{PROV}used", "is_iri": True, "object": used_e})

            for gen_e in activity.get("generated", []):
                triples.append({"subject": ai_iri, "predicate": f"{PROV}generated", "is_iri": True, "object": gen_e})

        return triples

    def finish(self) -> dict:
        duration = (datetime.datetime.now(tz=timezone.utc) - self._run_started).total_seconds()
        return {
            "run_id": self._run_id,
            "run_iri": self._run_iri,
            "started": self._run_started.isoformat(),
            "duration_seconds": duration,
            "entities_tracked": len(self._entities),
            "activities_logged": len(self._activities),
            "triples_generated": len(self.generate_triples()),
        }
