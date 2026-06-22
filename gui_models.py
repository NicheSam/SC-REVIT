from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict


@dataclass
class RfaTask:
    path: Path
    status: str = "等待讀取"
    result: Dict[str, Any] | None = None
    error: str | None = None
    approved_path: str | None = None
    planned_name: str | None = None
    planned_name_manual: bool = False
    base_name: str | None = None
    suffix_options: list[dict[str, object]] = field(default_factory=list)
    duplicate_result: Dict[str, Any] | None = None
    ingested_path: str | None = None
    standardization_result: Dict[str, Any] | None = None
    future_actions: list[str] = field(default_factory=list)

    @property
    def file_name(self) -> str:
        return self.path.name
