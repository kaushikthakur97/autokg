from __future__ import annotations

import logging
import re
from typing import Any, Optional

import polars as pl

_logger = logging.getLogger(__name__)


class ConversationContext:
    def __init__(self):
        self.history: list[dict] = []
        self.current_focus: Optional[str] = None
        self.last_result: Optional[list[dict]] = None
        self.last_question: Optional[str] = None
        self.entities_in_scope: list[str] = []
        self.active_filters: dict[str, Any] = {}
        self.turn_count: int = 0

    def record(self, question: str, result: list[dict], focus: Optional[str] = None):
        self.turn_count += 1
        self.history.append({
            "turn": self.turn_count,
            "question": question,
            "result_sample": result[:3] if len(result) > 3 else result,
            "result_count": len(result),
        })
        self.last_question = question
        self.last_result = result
        if focus:
            self.current_focus = focus
        if result:
            iri_key = next((k for k in result[0] if "iri" in k.lower() or "subject" in k.lower()), None)
            if iri_key:
                self.entities_in_scope = [r.get(iri_key, "") for r in result[:20]]

    def reset(self):
        self.__init__()

    def resolve_reference(self, text: str) -> Optional[str]:
        pronouns = {
            "they": "entities_in_scope", "them": "entities_in_scope",
            "it": "current_focus", "that": "current_focus",
            "this": "current_focus", "those": "entities_in_scope",
            "these": "entities_in_scope",
        }
        lowered = text.lower().strip()
        for pronoun, target in pronouns.items():
            if lowered.startswith(pronoun + " ") or lowered == pronoun:
                if target == "current_focus" and self.current_focus:
                    return self.current_focus
                if target == "entities_in_scope" and self.entities_in_scope:
                    return self.entities_in_scope[-1] if self.entities_in_scope else None
        return None

    def augment_question(self, question: str) -> str:
        if self.turn_count == 0:
            return question
        ref = self.resolve_reference(question)
        if ref:
            return f"{question} (referring to {ref})"
        return question

    def get_summary(self) -> dict:
        return {
            "turns": self.turn_count,
            "last_question": self.last_question,
            "entities_in_scope": len(self.entities_in_scope),
            "active_filters": self.active_filters,
        }
