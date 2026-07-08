from __future__ import annotations

from typing import Optional

import polars as pl


class EntityResolver:
    MATCH_EXACT = "exact"
    MATCH_FUZZY = "fuzzy"
    MATCH_PHONETIC = "phonetic"

    def __init__(self, knowledge_graph):
        self.kg = knowledge_graph
        self._matches: list[dict] = []
        self._linked_pairs: list[tuple[str, str]] = []

    def match(
        self,
        source_a: str,
        source_b: str,
        on: list[str],
        strategy: str = "exact",
        threshold: float = 0.85,
    ) -> list[dict]:
        df_a = self._get_dataframe(source_a)
        df_b = self._get_dataframe(source_b)

        if df_a is None or df_b is None:
            return []

        self._matches = []

        for col in on:
            if col not in df_a.columns or col not in df_b.columns:
                continue

            vals_a = set(df_a[col].drop_nulls().to_list())
            vals_b = set(df_b[col].drop_nulls().to_list())

            if strategy == self.MATCH_EXACT:
                common = vals_a & vals_b
                for val in common:
                    self._matches.append({"column": col, "value": val, "strategy": strategy})
                    iri_a = self._build_iri(source_a, val)
                    iri_b = self._build_iri(source_b, val)
                    self._linked_pairs.append((iri_a, iri_b))

            elif strategy == self.MATCH_FUZZY:
                for va in vals_a:
                    va_str = str(va).lower()
                    for vb in vals_b:
                        vb_str = str(vb).lower()
                        similarity = self._string_similarity(va_str, vb_str)
                        if similarity >= threshold:
                            self._matches.append({"column": col, "value_a": va, "value_b": vb, "strategy": strategy, "score": similarity})
                            self._linked_pairs.append((self._build_iri(source_a, va), self._build_iri(source_b, vb)))

            elif strategy == self.MATCH_PHONETIC:
                for va in vals_a:
                    va_phonetic = self._metaphone(str(va))
                    for vb in vals_b:
                        vb_phonetic = self._metaphone(str(vb))
                        if va_phonetic and vb_phonetic and va_phonetic == vb_phonetic:
                            self._matches.append({"column": col, "value_a": va, "value_b": vb, "strategy": strategy})
                            self._linked_pairs.append((self._build_iri(source_a, va), self._build_iri(source_b, vb)))

        return self._matches

    def link(self) -> int:
        triples: list[dict] = []
        owl_same_as = "http://www.w3.org/2002/07/owl#sameAs"
        for iri_a, iri_b in self._linked_pairs:
            triples.append({"subject": iri_a, "predicate": owl_same_as, "is_iri": True, "object": iri_b})

        if hasattr(self.kg, "_mapper") and self.kg._mapper is not None:
            self.kg._mapper.add_triples(triples)

        return len(triples)

    @property
    def match_count(self) -> int:
        return len(self._matches)

    @property
    def linked_count(self) -> int:
        return len(self._linked_pairs)

    def summary(self) -> dict:
        return {
            "matches_found": len(self._matches),
            "pairs_linked": len(self._linked_pairs),
            "matches": self._matches[:20],
        }

    def _get_dataframe(self, source_name: str) -> Optional[pl.DataFrame]:
        if hasattr(self.kg, "_tables") and source_name in self.kg._tables:
            return self.kg._tables[source_name].get("df")
        return None

    def _build_iri(self, source_name: str, value) -> str:
        ns = getattr(self.kg, "namespace", "http://example.org/")
        entity = self.kg._tables.get(source_name, {}).get("entity_type", source_name) if hasattr(self.kg, "_tables") else source_name
        return f"{ns.rstrip('/')}/{entity}/{value}"

    @staticmethod
    def _string_similarity(a: str, b: str) -> float:
        if not a or not b:
            return 0.0
        if a == b:
            return 1.0
        from difflib import SequenceMatcher
        return SequenceMatcher(None, a, b).ratio()

    @staticmethod
    def _metaphone(s: str) -> Optional[str]:
        try:
            from metaphone import doublemetaphone
            return doublemetaphone(s)[0]
        except ImportError:
            return s.lower()
