"""One-shot CLI to build or refresh the RAG corpus for 50 curated countries.

Usage:
  uv run python scripts/ingest_corpus.py --all
  uv run python scripts/ingest_corpus.py --country JP
  uv run python scripts/ingest_corpus.py --country JP --passport GB
"""

import argparse
import logging
import sys

sys.path.insert(0, ".")

from backend.app.logging_config import setup_logging
from backend.app.rag.ingest import ingest_country

setup_logging("INFO")
logger = logging.getLogger(__name__)

COUNTRIES = [
    "US", "GB", "FR", "DE", "IT", "ES", "PT", "NL", "BE", "CH",
    "AT", "SE", "NO", "DK", "FI", "PL", "CZ", "HU", "GR", "RO",
    "JP", "KR", "CN", "TH", "VN", "SG", "MY", "ID", "PH", "IN",
    "AU", "NZ", "CA", "MX", "BR", "AR", "CL", "CO", "PE", "ZA",
    "NG", "KE", "EG", "MA", "AE", "SA", "TR", "IL", "JO", "QA",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest travel corpus into Qdrant")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="Ingest all 50 countries")
    group.add_argument("--country", metavar="ISO", help="Ingest a single country (e.g. JP)")
    parser.add_argument("--passport", default="US", help="Passport nationality (default: US)")
    args = parser.parse_args()

    targets = COUNTRIES if args.all else [args.country.upper()]
    total = 0
    for iso in targets:
        logger.info("Ingesting %s (passport=%s)…", iso, args.passport)
        n = ingest_country(iso, passport=args.passport)
        logger.info("%s: %d chunks upserted", iso, n)
        total += n

    logger.info("Done — %d total chunks upserted across %d countries", total, len(targets))


if __name__ == "__main__":
    main()
