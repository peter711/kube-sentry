#!/usr/bin/env python3
"""Run the offline eval suite and write a JSON + Markdown report.

Usage:
    python evals/run_evals.py                 # all offline evals
    python evals/run_evals.py -k proposal     # filter by test id substring
    python evals/run_evals.py -m live         # live evals (cluster + deployed agent)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import pytest

EVALS_DIR = Path(__file__).resolve().parent
DEFAULT_REPORT_DIR = EVALS_DIR / "reports"


class _ReportPlugin:
    def __init__(self) -> None:
        self.results: list[dict[str, Any]] = []

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        if report.when == "call" or (report.when == "setup" and report.outcome in {"failed", "skipped"}):
            self.results.append(
                {
                    "nodeid": report.nodeid,
                    "outcome": report.outcome,
                    "duration_seconds": round(report.duration, 4),
                    "failure": str(report.longrepr) if report.failed else None,
                }
            )


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the kube-sentry eval suite.")
    parser.add_argument("-k", dest="keyword", default=None, help="only run tests matching this substring expression")
    parser.add_argument("-m", dest="marker", default="not live", help="pytest marker expression (default: 'not live')")
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR), help="directory for JSON/Markdown reports")
    parser.add_argument("--no-report", action="store_true", help="skip writing report files")
    return parser.parse_args(argv)


def _write_report(results: list[dict[str, Any]], duration: float, exit_code: int, report_dir: Path) -> Path:
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    report_dir.mkdir(parents=True, exist_ok=True)
    passed = sum(1 for item in results if item["outcome"] == "passed")
    failed = sum(1 for item in results if item["outcome"] == "failed")
    skipped = sum(1 for item in results if item["outcome"] == "skipped")
    summary = {
        "generated_at": timestamp,
        "duration_seconds": round(duration, 3),
        "exit_code": exit_code,
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "pass_rate": round(passed / len(results), 4) if results else 0.0,
        "results": results,
    }
    json_path = report_dir / f"{timestamp}.json"
    json_path.write_text(json.dumps(summary, indent=2))

    lines = [
        f"# Kube Sentry eval report ({timestamp})",
        "",
        f"- Total: {summary['total']}",
        f"- Passed: {passed}",
        f"- Failed: {failed}",
        f"- Skipped: {skipped}",
        f"- Pass rate: {summary['pass_rate']:.0%}",
        f"- Duration: {summary['duration_seconds']}s",
        "",
    ]
    if failed:
        lines.append("## Failures")
        lines.append("")
        for item in results:
            if item["outcome"] == "failed":
                lines.append(f"### `{item['nodeid']}`")
                lines.append("")
                lines.append("```")
                lines.append((item["failure"] or "").strip()[:4000])
                lines.append("```")
                lines.append("")
    (report_dir / f"{timestamp}.md").write_text("\n".join(lines))
    return json_path


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    plugin = _ReportPlugin()
    pytest_args = [str(EVALS_DIR), "-v", "-m", args.marker, "-p", "no:cacheprovider"]
    if args.keyword:
        pytest_args += ["-k", args.keyword]

    started = time.perf_counter()
    exit_code = pytest.main(pytest_args, plugins=[plugin])
    duration = time.perf_counter() - started

    if not args.no_report:
        json_path = _write_report(plugin.results, duration, int(exit_code), Path(args.report_dir))
        print(f"\nReport written to {json_path}")
    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
