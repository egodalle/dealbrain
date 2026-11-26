"""Entry point: run all four Philly ingestion pipelines (or a named subset)."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Any

import psycopg

from pipelines.base import BasePipeline, IngestResult
from pipelines.delinquency import DelinquencyPipeline
from pipelines.opa import OPAPipeline
from pipelines.transfers import TransfersPipeline
from pipelines.violations import ViolationsPipeline

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s — %(message)s")
logger = logging.getLogger(__name__)

_ALL_PIPELINES: dict[str, type[BasePipeline]] = {
    "opa": OPAPipeline,
    "violations": ViolationsPipeline,
    "transfers": TransfersPipeline,
    "delinquency": DelinquencyPipeline,
}


def _build_pipelines(dataset: str) -> list[BasePipeline]:
    if dataset in ("philly", "all"):
        return [cls() for cls in _ALL_PIPELINES.values()]
    if dataset in _ALL_PIPELINES:
        return [_ALL_PIPELINES[dataset]()]
    logger.error("Unknown dataset: %s", dataset)
    sys.exit(1)


def _print_summary(results: list[IngestResult]) -> None:
    header = f"{'dataset':<15} {'fetched':>8} {'inserted':>9} {'elapsed':>9}  status"
    print(header)
    print("-" * len(header))
    for r in results:
        status = "skipped" if r.skipped else ("error" if r.error else "ok")
        print(
            f"{r.dataset:<15} {r.rows_fetched:>8} {r.rows_inserted:>9} "
            f"{r.elapsed_seconds:>8.1f}s  {status}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Philly open-data ingestion pipelines")
    parser.add_argument(
        "--dataset",
        default="philly",
        choices=list(_ALL_PIPELINES.keys()) + ["philly", "all"],
        help="Which dataset to ingest (default: philly = all four)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch but do not write to the database",
    )
    args = parser.parse_args(argv)

    database_url = os.environ.get("DATABASE_URL")
    if not database_url and not args.dry_run:
        logger.error("DATABASE_URL env var is required (unless --dry-run)")
        return 1

    pipelines = _build_pipelines(args.dataset)
    results: list[IngestResult] = []

    if args.dry_run and not database_url:
        # Dry-run without a DB: just fetch and hash, no DB connection needed.
        for pipeline in pipelines:
            import time

            t0 = time.monotonic()
            rows_fetched = 0
            for page in pipeline.fetch_pages():
                rows_fetched += len(page)
            elapsed = time.monotonic() - t0
            results.append(
                IngestResult(
                    run_id="dry-run",
                    dataset=pipeline.dataset,
                    rows_fetched=rows_fetched,
                    rows_inserted=0,
                    rows_updated_staging=0,
                    rows_updated_core=0,
                    elapsed_seconds=elapsed,
                    skipped=True,
                )
            )
    else:
        assert database_url is not None
        conn: psycopg.Connection[Any]
        with psycopg.connect(database_url) as conn:
            for pipeline in pipelines:
                result = pipeline.run(conn, dry_run=args.dry_run)
                results.append(result)
                if result.error:
                    logger.error("[%s] completed with error: %s", pipeline.dataset, result.error)

    _print_summary(results)

    any_error = any(r.error for r in results)
    return 1 if any_error else 0


if __name__ == "__main__":
    sys.exit(main())
