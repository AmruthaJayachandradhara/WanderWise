"""Scheduled staleness refresh — re-ingests only changed documents.

Invoked by .github/workflows/reingest.yml on a per-collection cadence
(advisories daily, visa_entry weekly, destination_guides monthly), and
runnable locally:

  uv run python scripts/reingest.py --collections advisories
  uv run python scripts/reingest.py --collections visa_entry advisories --country JP

Exits non-zero if any country's refresh recorded errors.
"""

import argparse
import logging
import sys

sys.path.insert(0, ".")

from backend.app.logging_config import setup_logging
from backend.app.rag.collections import COLLECTION_CONFIGS
from backend.app.rag.staleness import refresh_country
from scripts.ingest_corpus import COUNTRIES

setup_logging("INFO")
logger = logging.getLogger(__name__)


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresh stale RAG corpus documents")
    parser.add_argument(
        "--collections",
        nargs="+",
        required=True,
        choices=sorted(COLLECTION_CONFIGS),
        help="Collections to refresh this run",
    )
    parser.add_argument("--country", metavar="ISO", help="Single country (default: all 50)")
    parser.add_argument("--passport", default="US", help="Passport nationality (default: US)")
    args = parser.parse_args()

    targets = [args.country.upper()] if args.country else COUNTRIES
    totals = {"unchanged": 0, "new": 0, "deleted": 0}
    errors: list[str] = []

    for iso in targets:
        report = refresh_country(iso, passport=args.passport, collections=args.collections)
        totals["unchanged"] += report.unchanged_chunks
        totals["new"] += report.new_chunks
        totals["deleted"] += report.deleted_chunks
        errors.extend(f"{iso}: {e}" for e in report.errors)

    logger.info(
        "Reingest complete (%s over %d countr%s): %d unchanged, %d re-ingested, %d deleted, %d error(s)",
        "+".join(args.collections),
        len(targets),
        "y" if len(targets) == 1 else "ies",
        totals["unchanged"],
        totals["new"],
        totals["deleted"],
        len(errors),
    )
    for e in errors:
        logger.error("  %s", e)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
