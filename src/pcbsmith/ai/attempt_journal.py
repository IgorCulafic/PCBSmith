"""Retained, redacted diagnostics for one local planning attempt."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from uuid import uuid4

from pcbsmith.operations.file_transaction import atomic_write


class AttemptJournal:
    """Unique directories keep failed retries from masquerading as an earlier success."""

    def __init__(self, output_dir: Path, *, secret: str | None = None) -> None:
        self.run_id = uuid4().hex
        self.directory = output_dir / "attempts" / self.run_id
        self.directory.mkdir(parents=True, exist_ok=False)
        self.path = self.directory / "agent-events.jsonl"
        self.secret = secret
        self.sequence = 0

    def redact(self, value: Any) -> Any:
        if isinstance(value, dict):
            return {
                str(key): "[REDACTED]"
                if str(key).lower().replace("-", "_")
                in {
                    "api_key",
                    "apikey",
                    "authorization",
                    "password",
                    "access_token",
                    "refresh_token",
                    "secret",
                }
                else self.redact(child)
                for key, child in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [self.redact(child) for child in value]
        if isinstance(value, str) and self.secret:
            return value.replace(self.secret, "[REDACTED]")
        return value

    def append(self, event: str, **fields: Any) -> None:
        payload = self.redact(
            {
                "schema": "pcbsmith-agent-event-v1",
                "run_id": self.run_id,
                "sequence": self.sequence,
                "event": event,
                **fields,
            }
        )
        data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        with self.path.open("ab") as handle:
            if handle.write(data) != len(data):
                raise OSError("Incomplete agent-event write")
            handle.flush()
            os.fsync(handle.fileno())
        self.sequence += 1

    def raw(self, event: str, payload: bytes) -> None:
        text = payload.decode("utf-8", errors="replace")
        try:
            content = json.loads(text)
        except ValueError:
            content = text
        self.append(event, content=content, redacted=True)

    def checkpoint(self, steps: list[dict[str, Any]], *, status: str) -> None:
        payload = self.redact(
            {
                "schema": "pcbsmith-local-agent-transcript-v1",
                "run_id": self.run_id,
                "status": status,
                "steps": steps,
            }
        )
        atomic_write(
            self.directory / "agent-transcript.json",
            (json.dumps(payload, indent=2) + "\n").encode("utf-8"),
        )
