from __future__ import annotations

from collections import Counter
from typing import Any, Optional

import polars as pl


class GraphProfiler:
    def __init__(self, knowledge_graph):
        self.kg = knowledge_graph

    def profile(self) -> pl.DataFrame:
        metrics: dict[str, Any] = {
            "total_triples": self._count_triples(),
            "total_entities": 0,
            "entity_types": 0,
            "distinct_predicates": 0,
            "distinct_objects": 0,
            "orphan_entities": 0,
            "broken_references": 0,
            "literal_columns": 0,
            "relationship_edges": 0,
        }

        counts = self._detailed_counts()
        if counts:
            metrics.update(counts)

        rows: list[dict] = [{"metric": k, "value": v} for k, v in metrics.items()]
        return pl.DataFrame(rows)

    def class_distribution(self) -> pl.DataFrame:
        triples = self._get_triples()
        if not triples:
            return pl.DataFrame({})

        rdf_type = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
        type_counts: Counter = Counter()
        for t in triples:
            if t.get("predicate") == rdf_type or t.get("predicate") == "a":
                obj = t.get("object", "Unknown")
                label = obj.split("/")[-1] if "/" in obj else obj.split("#")[-1] if "#" in obj else obj
                type_counts[label] += 1

        rows = [{"class": cls, "count": cnt} for cls, cnt in type_counts.most_common()]
        return pl.DataFrame(rows)

    def property_distribution(self) -> pl.DataFrame:
        triples = self._get_triples()
        if not triples:
            return pl.DataFrame({})

        prop_counts: Counter = Counter()
        for t in triples:
            prop = t.get("predicate", "")
            prop_counts[prop] += 1

        rows = [{"property": prop, "count": cnt} for prop, cnt in prop_counts.most_common()]
        return pl.DataFrame(rows)

    def diagnose(self) -> dict:
        triples = self._get_triples()
        issues: list[dict] = []
        warnings: list[dict] = []
        info: list[dict] = []

        subjects = set()
        objects_iri = set()
        predicate_set = set()
        subjects_by_type: dict[str, set] = {}

        rdf_type = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"

        for t in triples:
            subj = t.get("subject", "")
            pred = t.get("predicate", "")
            obj = t.get("object", "")

            subjects.add(subj)
            predicate_set.add(pred)

            if t.get("is_iri") or t.get("object_iri"):
                objects_iri.add(obj)

            if pred == rdf_type:
                label = obj.split("/")[-1] if "/" in obj else obj.split("#")[-1] if "#" in obj else obj
                if label not in subjects_by_type:
                    subjects_by_type[label] = set()
                subjects_by_type[label].add(subj)

        subjects_referenced = set()
        for t in triples:
            if t.get("is_iri") or t.get("object_iri"):
                obj = t.get("object", "")
                if obj in subjects or obj not in subjects:
                    subjects_referenced.add(obj)

        orphan_count = len(subjects - subjects_referenced)

        info.append({"type": "info", "message": f"Total subjects: {len(subjects)}"})
        info.append({"type": "info", "message": f"Distinct predicates: {len(predicate_set)}"})
        info.append({"type": "info", "message": f"Distinct by-type classes: {len(subjects_by_type)}"})

        if orphan_count > 0:
            warnings.append({"type": "warning", "message": f"{orphan_count} entities have no incoming references", "count": orphan_count})

        info.append({"type": "info", "message": f"Total triples analyzed: {len(triples)}"})

        return {"issues": issues, "warnings": warnings, "info": info}

    def _count_triples(self) -> int:
        if hasattr(self.kg, "_mapper") and self.kg._mapper:
            return self.kg._mapper.count_triples()
        return len(self._get_triples())

    def _get_triples(self) -> list[dict]:
        if hasattr(self.kg, "_mapper") and self.kg._mapper:
            return self.kg._mapper.get_triples()
        return []

    def _detailed_counts(self) -> Optional[dict]:
        triples = self._get_triples()
        if not triples:
            return None

        subjects = set()
        objects = set()
        predicates = set()

        for t in triples:
            subjects.add(t.get("subject", ""))
            predicates.add(t.get("predicate", ""))
            if t.get("is_iri") or t.get("object_iri"):
                objects.add(t.get("object", ""))
            else:
                objects.add(t.get("object", ""))

        return {
            "total_entities": len(subjects),
            "distinct_predicates": len(predicates),
            "distinct_objects": len(objects),
        }
