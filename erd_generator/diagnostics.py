"""Diagnostics shared by SQL and configuration adapters."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ParseFailure:
    source: str | None
    sql: str
    reason: str
    severity: str = "error"
    line: int | None = None

    @property
    def location(self) -> str:
        source = self.source or "<input>"
        return f"{source}:{self.line}" if self.line is not None else source
