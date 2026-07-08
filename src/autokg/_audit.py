from __future__ import annotations

import datetime
import json
import logging
import uuid
from datetime import timezone
from pathlib import Path
from typing import Any, Optional

import polars as pl

_logger = logging.getLogger(__name__)


class AuditEvent:
    def __init__(
        self,
        action: str,
        actor: str = "unknown",
        details: Optional[dict] = None,
        ticket_ref: str = "",
        event_id: Optional[str] = None,
        timestamp: Optional[str] = None,
    ):
        self.event_id = event_id or str(uuid.uuid4())
        self.timestamp = timestamp or datetime.datetime.now(tz=timezone.utc).isoformat()
        self.actor = actor
        self.action = action
        self.details = details or {}
        self.ticket_ref = ticket_ref


class AuditTrail:
    def __init__(self, log_path: Optional[str] = None, openlineage_endpoint: Optional[str] = None):
        self.log_path = Path(log_path) if log_path else None
        self.openlineage_endpoint = openlineage_endpoint
        self._events: list[AuditEvent] = []
        self._openlineage_client = None
        self._run_id = str(uuid.uuid4())
        self._pipeline_name = "autokg"

        if log_path:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            if self.log_path.exists():
                self._load_existing()

        if openlineage_endpoint:
            self._init_openlineage()

    def record(self, action: str, actor: str = "unknown", details: Optional[dict] = None, ticket_ref: str = "") -> AuditEvent:
        event = AuditEvent(action=action, actor=actor, details=details, ticket_ref=ticket_ref)
        self._events.append(event)
        self._persist(event)
        self._emit_openlineage(event)
        return event

    def log(self) -> pl.DataFrame:
        rows = [
            {
                "timestamp": e.timestamp,
                "actor": e.actor,
                "action": e.action,
                "details": json.dumps(e.details, default=str),
                "ticket_ref": e.ticket_ref,
                "event_id": e.event_id,
            }
            for e in self._events
        ]
        return pl.DataFrame(rows) if rows else pl.DataFrame({})

    def filter(self, action: Optional[str] = None, actor: Optional[str] = None,
               since: Optional[str] = None, until: Optional[str] = None) -> list[AuditEvent]:
        results = self._events
        if action:
            results = [e for e in results if e.action == action]
        if actor:
            results = [e for e in results if actor.lower() in e.actor.lower()]
        if since:
            results = [e for e in results if e.timestamp >= since]
        if until:
            results = [e for e in results if e.timestamp <= until]
        return results

    def who_changed(self, entity_iri: str) -> list[AuditEvent]:
        return [e for e in self._events if entity_iri in json.dumps(e.details, default=str)]

    def event_count(self) -> int:
        return len(self._events)

    def _persist(self, event: AuditEvent):
        if not self.log_path:
            return
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "event_id": event.event_id,
                    "timestamp": event.timestamp,
                    "actor": event.actor,
                    "action": event.action,
                    "details": event.details,
                    "ticket_ref": event.ticket_ref,
                }, default=str) + "\n")
        except Exception as e:
            _logger.warning("Failed to persist audit event: %s", e)

    def _load_existing(self):
        if not self.log_path or not self.log_path.exists():
            return
        try:
            for line in self.log_path.read_text(encoding="utf-8").strip().split("\n"):
                if not line.strip():
                    continue
                data = json.loads(line)
                self._events.append(AuditEvent(
                    event_id=data.get("event_id", str(uuid.uuid4())),
                    timestamp=data.get("timestamp", ""),
                    actor=data.get("actor", "unknown"),
                    action=data.get("action", ""),
                    details=data.get("details", {}),
                    ticket_ref=data.get("ticket_ref", ""),
                ))
        except Exception as e:
            _logger.warning("Failed to load existing audit log: %s", e)

    def _init_openlineage(self):
        try:
            from openlineage.client import OpenLineageClient
            from openlineage.client.run import RunEvent, RunState, Run, Job
            from openlineage.client.facet import NominalTimeRunFacet

            self._openlineage_client = OpenLineageClient(url=self.openlineage_endpoint)
            _logger.info("OpenLineage client initialized at %s", self.openlineage_endpoint)
        except ImportError:
            _logger.info("openlineage-python not installed. Install with: pip install openlineage-python")
        except Exception as e:
            _logger.warning("Failed to initialize OpenLineage client: %s", e)

    def _emit_openlineage(self, event: AuditEvent):
        if not self._openlineage_client:
            return
        try:
            from openlineage.client.run import RunEvent, RunState, Run, Job
            from openlineage.client.facet import NominalTimeRunFacet, ParentRunFacet

            job = Job(namespace=self._pipeline_name, name=f"autokg.{event.action}")
            run = Run(runId=self._run_id)
            run_event = RunEvent(
                eventType=RunState.COMPLETE if "error" not in str(event.details).lower() else RunState.FAIL,
                eventTime=event.timestamp,
                run=run,
                job=job,
                producer=f"autokg/{self._pipeline_name}",
            )
            self._openlineage_client.emit(run_event)
        except Exception as e:
            _logger.debug("Failed to emit OpenLineage event: %s", e)
