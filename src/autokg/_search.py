from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import polars as pl

_logger = logging.getLogger(__name__)


class KGSearcher:
    def __init__(self, knowledge_graph, embedding_model: str = "all-MiniLM-L6-v2", zvec_path: Optional[str] = None):
        self.kg = knowledge_graph
        self.embedding_model_name = embedding_model
        self.zvec_path = zvec_path
        self._collection = None
        self._embedder = None
        self._indexed: bool = False

    def _get_embedder(self):
        if self._embedder is None:
            try:
                from sentence_transformers import SentenceTransformer
                self._embedder = SentenceTransformer(self.embedding_model_name)
            except ImportError:
                raise ImportError("sentence-transformers required for semantic search. Install with: pip install sentence-transformers")
        return self._embedder

    def _get_collection(self):
        if self._collection is None:
            try:
                import zvec
            except ImportError:
                raise ImportError("zvec required for vector search. Install with: pip install zvec")
            collection_path = self.zvec_path or str(Path(self.kg.store_path or ".") / "_autokg_zvec")
            try:
                schema = zvec.CollectionSchema(
                    name="autokg_entities",
                    vectors=zvec.VectorSchema("embedding", zvec.DataType.VECTOR_FP32, 384),
                )
                self._collection = zvec.create_and_open(path=collection_path, schema=schema)
            except Exception:
                self._collection = zvec.open_collection(collection_path)
        return self._collection

    def index(self, entity_types: Optional[list[str]] = None, property_filter: Optional[list[str]] = None):
        embedder = self._get_embedder()
        collection = self._get_collection()
        triples = self.kg._mapper.get_triples()

        entities: dict[str, dict] = {}
        for t in triples:
            subj = t.get("subject", "")
            pred = t.get("predicate", "")
            obj = str(t.get("object", ""))
            if t.get("is_iri") or t.get("object_iri"):
                continue
            if entity_types and not any(et.lower() in subj.lower() for et in entity_types):
                continue
            if property_filter and not any(pf.lower() in pred.lower() for pf in property_filter):
                continue
            if subj not in entities:
                entities[subj] = {"iri": subj, "properties": {}}
            entities[subj]["properties"][pred] = obj

        texts: list[str] = []
        entity_list: list[dict] = []
        for iri, entity in entities.items():
            prop_text = " ".join(f"{v}" for v in entity["properties"].values())
            texts.append(prop_text)
            entity_list.append(entity)

        if not texts:
            _logger.warning("No entities to index")
            return 0

        embeddings = embedder.encode(texts, show_progress_bar=False)
        docs = []
        for i, entity in enumerate(entity_list):
            docs.append(zvec.zvec.Doc(
                id=entity["iri"],
                vectors={"embedding": embeddings[i].tolist()},
            ))
        collection.insert(docs)
        self._indexed = True
        _logger.info("Indexed %d entities", len(docs))
        return len(docs)

    def search(self, query: str, top_k: int = 10, entity_type: Optional[str] = None):
        embedder = self._get_embedder()
        collection = self._get_collection()
        query_embedding = embedder.encode([query], show_progress_bar=False)[0]

        import zvec
        results = collection.query(
            zvec.Query(field_name="embedding", vector=query_embedding.tolist()),
            topk=top_k,
        )

        matches: list[dict] = []
        for r in results:
            iri = r.get("id", "")
            if entity_type and entity_type.lower() not in iri.lower():
                continue
            matches.append({"iri": iri, "score": r.get("score", 0)})
        return matches

    def find_similar(self, entity_iri: str, top_k: int = 10):
        triples = self.kg._mapper.get_triples()
        entity_text_parts: list[str] = []
        for t in triples:
            if t.get("subject") == entity_iri:
                if not t.get("is_iri") and not t.get("object_iri"):
                    entity_text_parts.append(str(t.get("object", "")))
        query = " ".join(entity_text_parts)
        if not query:
            return []
        return self.search(query, top_k=top_k)

    def semantic_match(self, source_a_iris: list[str], source_b_iris: list[str], threshold: float = 0.85):
        pairs: list[dict] = []
        for iri_a in source_a_iris:
            similar = self.find_similar(iri_a, top_k=5)
            for match in similar:
                if match["iri"] in source_b_iris and match["score"] >= threshold:
                    pairs.append({"iri_a": iri_a, "iri_b": match["iri"], "score": match["score"]})
        return pairs
