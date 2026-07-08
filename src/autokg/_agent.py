from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Optional

import polars as pl

_agent_logger = logging.getLogger(__name__)


class GraphAgent:
    def __init__(
        self,
        knowledge_graph,
        provider: str = "openai",
        model: str = "gpt-4o",
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        verbose: bool = False,
    ):
        self.kg = knowledge_graph
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.verbose = verbose
        self._ontology_summary: Optional[str] = None
        self._examples: Optional[str] = None
        self._conversation_history: list[dict] = []

    def ask(self, question: str, max_rows: int = 50) -> pl.DataFrame:
        sparql = self._generate_sparql(question)
        if self.verbose:
            print(f"[GraphAgent] Generated SPARQL:\n{sparql}\n")
        return self._execute(sparql)

    def explain(self, question: str) -> tuple[str, str]:
        sparql = self._generate_sparql(question)
        return sparql, f"Question: {question}"

    def explain_full(self, question: str) -> dict:
        sparql = self._generate_sparql(question)
        result = self._execute(sparql)
        return {
            "question": question,
            "sparql": sparql,
            "result_count": result.height if result is not None else 0,
            "confidence": self._compute_confidence(sparql),
            "suggested_followups": self._suggest_followups(question, result),
        }

    def _compute_confidence(self, sparql: str) -> float:
        score = 0.5
        if "FILTER" in sparql.upper():
            score += 0.1
        if "GROUP BY" in sparql.upper():
            score += 0.1
        if "ORDER BY" in sparql.upper():
            score += 0.05
        if "SELECT" in sparql.upper() and "WHERE" in sparql.upper():
            score += 0.15
        if sparql.count("{") == sparql.count("}") and sparql.count("{") > 0:
            score += 0.1
        return min(score, 0.95)

    def _suggest_followups(self, question: str, result: Optional[pl.DataFrame]) -> list[str]:
        suggestions: list[str] = []
        if result is None or result.height == 0:
            return ["Can you rephrase your question?", "Try asking about specific entities or properties."]
        if result.height > 10:
            suggestions.append(f"Can you filter these {result.height} results by a specific criteria?")
        if result.height > 1:
            suggestions.append("Which of these has the highest value?")
        suggestions.append("Show me more details about the first result.")
        if "order" in question.lower():
            suggestions.append("Show me the customers who placed these orders.")
        if "customer" in question.lower():
            suggestions.append("Show me all orders for these customers.")
        return suggestions[:3]

    def rag(self, question: str, depth: int = 2, max_results: int = 10) -> str:
        summary = self._get_ontology_summary()
        entities = self._extract_entities_from_question(question, summary)

        context_parts: list[str] = []
        for entity_text in entities[:max_results]:
            fragments = self._traverse_subgraph(entity_text, depth=depth)
            if fragments:
                context_parts.append("\n".join(fragments))

        context = "\n\n".join(context_parts)
        prompt = f"""You are a knowledge graph analyst. Answer the question using ONLY the graph data below.

GRAPH DATA:
{context}

QUESTION: {question}

Answer concisely using only information present in the graph data. If the data doesn't contain an answer, say so."""
        return self._call_llm(prompt)

    def _generate_sparql(self, question: str) -> str:
        summary = self._get_ontology_summary()
        examples = self._get_examples()

        prompt = f"""You are a SPARQL query generator. Generate a valid SPARQL SELECT query for the following question.

ONTOLOGY:
{summary}

EXAMPLES:
{examples}

QUESTION: {question}

Return ONLY the SPARQL query, nothing else. No markdown, no explanation. Just the raw SPARQL."""

        response = self._call_llm(prompt)
        query = self._extract_sparql(response)
        if not query.strip().upper().startswith(("SELECT", "PREFIX", "CONSTRUCT", "ASK", "DESCRIBE")):
            query = "SELECT * WHERE { ?s ?p ?o } LIMIT 50"

        return query

    def _execute(self, sparql: str) -> pl.DataFrame:
        try:
            result = self.kg.query(sparql)
            if result is not None and result.height > 0:
                return result
        except Exception as e:
            if self.verbose:
                print(f"[GraphAgent] Query failed: {e}")

        return pl.DataFrame({})

    def _call_llm(self, prompt: str) -> str:
        try:
            import httpx
        except ImportError:
            self._ensure_httpx()
            import httpx

        if self.provider == "openai":
            return self._call_openai(prompt)
        elif self.provider == "ollama":
            return self._call_ollama(prompt)
        elif self.provider == "custom":
            return self._call_custom(prompt)
        else:
            return self._call_openai(prompt)

    def _call_openai(self, prompt: str) -> str:
        try:
            import openai
            client = openai.OpenAI(api_key=self.api_key)
            response = client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
            )
            return response.choices[0].message.content or ""
        except ImportError:
            return self._call_http(prompt, "https://api.openai.com/v1/chat/completions")

    def _call_ollama(self, prompt: str) -> str:
        base = self.base_url or "http://localhost:11434"
        return self._call_http(prompt, f"{base}/api/chat", is_ollama=True)

    def _call_custom(self, prompt: str) -> str:
        if not self.base_url:
            raise ValueError("base_url required for custom provider")
        return self._call_http(prompt, self.base_url)

    def _call_http(self, prompt: str, url: str, is_ollama: bool = False) -> str:
        import httpx

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        if is_ollama:
            body = {"model": self.model, "messages": [{"role": "user", "content": prompt}], "stream": False}
        else:
            body = {"model": self.model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.1}

        with httpx.Client(timeout=60) as client:
            response = client.post(url, json=body, headers=headers)

        data = response.json()
        if is_ollama:
            return data.get("message", {}).get("content", "")
        return data.get("choices", [{}])[0].get("message", {}).get("content", "")

    def _get_ontology_summary(self) -> str:
        if self._ontology_summary:
            return self._ontology_summary

        parts: list[str] = []
        if hasattr(self.kg, "_tables"):
            for name, info in self.kg._tables.items():
                df = info.get("df")
                etype = info.get("entity_type", name)
                if df is not None:
                    cols = ", ".join(df.columns[:15])
                    parts.append(f"  Class: {etype} (table: {name})")
                    parts.append(f"    Columns: {cols}")
                    parts.append(f"    Rows: {df.height}")

        self._ontology_summary = "\n".join(parts) if parts else "No ontology loaded."
        return self._ontology_summary

    def _get_examples(self) -> str:
        return """Example 1:
Question: List all customers
SPARQL:
PREFIX ex: <http://example.org/>
PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>
SELECT ?customer ?name WHERE { ?customer a ex:Customer ; ex:name ?name }

Example 2:
Question: Find orders over $1000
SPARQL:
PREFIX ex: <http://example.org/>
SELECT ?order ?amount WHERE { ?order ex:amount ?amount . FILTER(?amount > 1000) }

Example 3:
Question: Which customers from Norway placed orders?
SPARQL:
PREFIX ex: <http://example.org/>
SELECT ?customer ?name ?order WHERE { ?customer ex:country "Norway" ; ex:name ?name . ?order ex:customer_id ?customer }"""

    def _extract_sparql(self, response: str) -> str:
        code_match = re.search(r"```(?:sparql)?\s*\n?(.*?)```", response, re.DOTALL | re.IGNORECASE)
        if code_match:
            return code_match.group(1).strip()
        return response.strip()

    def _extract_entities_from_question(self, question: str, summary: str) -> list[str]:
        keywords = question.lower().split()
        entities: set[str] = set()
        for word in keywords:
            if len(word) > 3:
                entities.add(word)
        return list(entities)[:10]

    def _traverse_subgraph(self, entity_text: str, depth: int = 2) -> list[str]:
        fragments: list[str] = []
        try:
            safe_text = entity_text.replace('\\', '\\\\').replace('"', '\\"').replace("'", "\\'")
            result = self.kg.query(f"""
                SELECT ?s ?p ?o WHERE {{
                    ?s ?p ?o .
                    FILTER(CONTAINS(LCASE(STR(?s)), "{safe_text}") || CONTAINS(LCASE(STR(?o)), "{safe_text}"))
                }} LIMIT 20
            """)
            if result is not None:
                for row in result.iter_rows(named=True):
                    fragments.append(f"{row.get('s', '')} {row.get('p', '')} {row.get('o', '')} .")
        except Exception as e:
            _agent_logger.warning("Subgraph traversal failed: %s", e)
        return fragments

    @staticmethod
    def _ensure_httpx():
        try:
            import httpx
        except ImportError:
            raise ImportError("httpx required for LLM integration. Install with: pip install httpx")


def create_agent(
    knowledge_graph,
    provider: str = "openai",
    model: str = "gpt-4o",
    api_key: Optional[str] = None,
    **kwargs,
) -> GraphAgent:
    return GraphAgent(knowledge_graph, provider=provider, model=model, api_key=api_key, **kwargs)
