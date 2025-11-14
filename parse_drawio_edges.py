#!/usr/bin/env python3
"""CLI to extract draw.io connections and emit FK-config-style YAML."""
from __future__ import annotations

import argparse
import logging
import sys
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import yaml

from erd_generator.drawio_parser import parse_drawio_edges

FATAL_ISSUES = {"missing start table", "missing start column", "missing end table"}


def _register_ordered_dict():
    from yaml.representer import SafeRepresenter
    try:
        yaml.add_representer(
            OrderedDict,
            lambda dumper, data: dumper.represent_mapping(
                SafeRepresenter.DEFAULT_MAPPING_TAG,
                data.items(),
            ),
            Dumper=yaml.SafeDumper,
        )
    except Exception:
        pass


_register_ordered_dict()


@dataclass(frozen=True)
class EdgeAnomaly:
    index: int
    edge: Dict[str, str]
    issues: Tuple[str, ...]
    fatal: bool


def _value_or_placeholder(raw: Optional[str], index: int, label: str) -> str:
    text = (raw or "").strip()
    if text:
        return text
    safe_label = label.upper().replace(" ", "_")
    return f"__MISSING_{safe_label}_{index}__"


def _format_endpoint(table: str, column: str) -> str:
    if table and column:
        return f"{table}.{column}"
    if table:
        return table
    if column:
        return f"[column:{column}]"
    return "<unresolved>"


def _describe_edge(edge: Dict[str, str]) -> str:
    return f"{_format_endpoint(edge.get('start_table', ''), edge.get('start_column', ''))} -> " \
        f"{_format_endpoint(edge.get('end_table', ''), edge.get('end_column', ''))}"


def _detect_anomalies(edges: Sequence[Dict[str, str]]) -> List[EdgeAnomaly]:
    anomalies: List[EdgeAnomaly] = []
    for idx, edge in enumerate(edges, start=1):
        start_table = (edge.get("start_table") or "").strip()
        start_column = (edge.get("start_column") or "").strip()
        end_table = (edge.get("end_table") or "").strip()
        end_column = (edge.get("end_column") or "").strip()

        issues: List[str] = []
        if not start_table:
            issues.append("missing start table")
        if start_table and not start_column:
            issues.append("missing start column")
        if not end_table:
            issues.append("missing end table")
        if end_table and not end_column:
            issues.append("missing end column")

        if issues:
            fatal = any(issue in FATAL_ISSUES for issue in issues)
            anomalies.append(EdgeAnomaly(index=idx, edge=edge, issues=tuple(issues), fatal=fatal))
    return anomalies


def _build_fk_config(edges: Sequence[Dict[str, str]]) -> dict:
    config: "OrderedDict[str, dict[str, List[List[str]]]]" = OrderedDict()
    for idx, edge in enumerate(edges, start=1):
        start_table = _value_or_placeholder(edge.get("start_table"), idx, "start_table")
        start_column = _value_or_placeholder(edge.get("start_column"), idx, "start_column")
        end_table = _value_or_placeholder(edge.get("end_table"), idx, "end_table")
        end_column = _value_or_placeholder(edge.get("end_column"), idx, "end_column")
        table_entry = config.setdefault(start_table, {"fks": []})
        table_entry["fks"].append([start_column, end_table, end_column])
    return config


def _setup_logging(level: str) -> None:
    logging.basicConfig(level=getattr(logging, level.upper(), logging.INFO), format="%(levelname)s: %(message)s")


def _log_anomalies(anomalies: Sequence[EdgeAnomaly]) -> None:
    if not anomalies:
        logging.info("No parse anomalies detected.")
        return
    fatal = [a for a in anomalies if a.fatal]
    non_fatal = [a for a in anomalies if not a.fatal]
    for anomaly in anomalies:
        log_fn = logging.warning if anomaly.fatal else logging.info
        log_fn(
            "Edge %d %s issues: %s",
            anomaly.index,
            _describe_edge(anomaly.edge),
            ", ".join(anomaly.issues),
        )
    logging.info(
        "Detected %d edges with issues (%d fatal, %d non-fatal).",
        len(anomalies),
        len(fatal),
        len(non_fatal),
    )


def _default_failure_log_path(drawio_path: Path) -> Path:
    return drawio_path.with_suffix(".edge_anomalies.log")


def _write_anomaly_log(anomalies: Sequence[EdgeAnomaly], path: Optional[Path]) -> None:
    if not path:
        return
    if not anomalies:
        logging.info("No anomalies detected; failure log not written.")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        handle.write("Edge anomalies captured by parse_drawio_edges\n\n")
        for anomaly in anomalies:
            handle.write(f"Edge {anomaly.index}: {_describe_edge(anomaly.edge)}\n")
            handle.write(f"Issues: {', '.join(anomaly.issues)}\n")
            handle.write(f"Severity: {'fatal' if anomaly.fatal else 'non-fatal'}\n\n")
    logging.info("Anomaly details written to %s", path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Parse a draw.io (.drawio) XML file and emit FK-config-style YAML."
    )
    parser.add_argument(
        "drawio_file",
        type=Path,
        help="Path to the .drawio XML file to parse",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Verbosity for anomaly logging (default: INFO).",
    )
    parser.add_argument(
        "--failure-log",
        type=Path,
        help="Path to write edge anomaly details (default: <drawio>.edge_anomalies.log).",
    )
    parser.add_argument(
        "--no-failure-log",
        action="store_true",
        help="Skip writing the edge anomaly log file.",
    )
    args = parser.parse_args(argv)

    if not args.drawio_file.exists():
        parser.error(f"File not found: {args.drawio_file}")

    _setup_logging(args.log_level)

    edges = parse_drawio_edges(str(args.drawio_file))
    anomalies = _detect_anomalies(edges)
    _log_anomalies(anomalies)
    log_path: Optional[Path] = None
    if not args.no_failure_log:
        log_path = args.failure_log or _default_failure_log_path(args.drawio_file)
    _write_anomaly_log(anomalies, log_path)

    config = _build_fk_config(edges)

    if not config:
        logging.error("No usable edges were detected; FK config YAML will be empty.")
    yaml.safe_dump(config, sys.stdout, sort_keys=False, allow_unicode=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
