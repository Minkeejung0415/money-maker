"""Audit and seal leakage-safe World Cup tactical calibration rows."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from alpha.data.ingestion.wc_tactical_history import audit_rows, build_rows_from_espn_cache, load_rows, write_dataset


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="Optional versioned source JSONL rows")
    parser.add_argument("--cache-dir", type=Path, default=Path("data/.wc_cache/espn_tactics"))
    parser.add_argument("--output", type=Path, default=Path("data/.wc_cache/tactical_history/v1"))
    parser.add_argument("--audit-cutoff", default=datetime.now(timezone.utc).isoformat())
    parser.add_argument("--report-only", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    cutoff = datetime.fromisoformat(args.audit_cutoff.replace("Z", "+00:00"))
    rows = load_rows(args.input) if args.input else build_rows_from_espn_cache(args.cache_dir)
    report = audit_rows(rows, audit_cutoff=cutoff)
    print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
    if args.report_only:
        return
    manifest = write_dataset(rows, args.output, audit_cutoff=cutoff)
    print(f"Manifest: {args.output / 'manifest.json'}")
    if not manifest["ready"]:
        print("Deployment blocked: dataset does not satisfy 200/50/30 gates.")


if __name__ == "__main__":
    main()
