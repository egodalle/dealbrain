from __future__ import annotations

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


class BaseConnector(ABC):
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def push(self, records: list[dict[str, Any]], conn: Any) -> list[PendingAction]: ...

    @abstractmethod
    def pull_changes(self, since: datetime | None = None) -> list[dict[str, Any]]: ...

    @abstractmethod
    def health_check(self) -> dict[str, str]: ...
