from __future__ import annotations

from typing import Any, Optional

import polars as pl


class Conversation:
    def __init__(self, knowledge_graph, provider: str = "openai", model: str = "gpt-4o", api_key: Optional[str] = None, base_url: Optional[str] = None, verbose: bool = False):
        self.kg = knowledge_graph
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.verbose = verbose
        self._turns: list[dict] = []
        self._last_entities: list[str] = []
        self._last_result: Optional[pl.DataFrame] = None
        self._last_filter: Optional[str] = None

    def ask(self, question: str) -> pl.DataFrame:
        from ._agent import GraphAgent

        augmented = self._augment(question)
        agent = GraphAgent(self.kg, provider=self.provider, model=self.model, api_key=self.api_key, base_url=self.base_url, verbose=self.verbose)

        try:
            result = agent.ask(augmented)
        except Exception:
            result = pl.DataFrame({})

        self._turns.append({
            "question": question,
            "augmented": augmented if augmented != question else None,
            "result_count": result.height if result is not None else 0,
        })

        if result is not None and result.height > 0:
            self._last_result = result
            first_col = result.columns[0] if result.columns else ""
            self._last_entities = result[first_col].to_list() if first_col else []

        return result

    def explain_last(self) -> tuple[str, Optional[str]]:
        if not self._turns:
            return "No questions asked yet.", None
        last = self._turns[-1]
        return last.get("augmented", last["question"]), last.get("question")

    def reset(self):
        self._turns = []
        self._last_entities = []
        self._last_result = None
        self._last_filter = None

    def _augment(self, question: str) -> str:
        q_lower = question.lower().strip()
        if not self._turns:
            return question

        followup_markers = [
            "which one", "which of", "what about", "how about",
            "and the", "and their", "their", "it", "they",
            "them", "those", "that one", "the same",
        ]
        is_followup = any(q_lower.startswith(m) for m in followup_markers)

        if is_followup and self._last_entities:
            refs = ", ".join(str(e) for e in self._last_entities[:5])
            suffix = f" them" if "?" in question else " for them"
            if "?" in question:
                parts = question.rsplit("?", 1)
                if len(parts) == 2 and not parts[1].strip():
                    return f"{parts[0]} for: {refs}"
            return f"{question} (referring to: {refs})"

        return question

    @property
    def turn_count(self) -> int:
        return len(self._turns)

    def summary(self) -> dict:
        return {
            "turns": len(self._turns),
            "history": self._turns[-5:],
        }
