from __future__ import annotations

import hashlib
import json
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class PendingAction:
    connector: str
    action_type: str
    payload: dict[str, Any]
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    status: str = "pending"
    created_at: datetime = field(default_factory=datetime.utcnow)
    approved_at: datetime | None = None
    sent_at: datetime | None = None

    @property
    def payload_hash(self) -> str:
        """MD5 of canonical JSON payload — mirrors the DB generated column."""
        return hashlib.md5(json.dumps(self.payload, sort_keys=True).encode()).hexdigest()


class BaseConnector(ABC):
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def push(self, records: list[dict[str, Any]], conn: Any = None) -> list[PendingAction]: ...

    @abstractmethod
    def pull_changes(self, since: datetime | None = None) -> list[dict[str, Any]]: ...

    @abstractmethod
    def health_check(self) -> dict[str, str]: ...
