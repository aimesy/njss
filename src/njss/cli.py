"""Command line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from njss.client import CivilView
from njss.collect import collect, export


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="njss", description="New Jersey sheriff sale capture")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("collect", help="Fetch listings and details, then export")
    run.add_argument("--data-dir", type=Path, default=Path("data"))
    run.add_argument("--counties", type=Path, default=Path("config/counties.json"))
    run.add_argument("--county", type=int, action="append", help="Limit to these county IDs")
    run.add_argument("--delay", type=float, default=0.75, help="Seconds between requests")
    run.add_argument("--refresh-days", type=int, default=7, help="Refetch open sale details this often")
    run.add_argument("--skip-closed", action="store_true", help="Skip the sold and cancelled list")

    out = sub.add_parser("export", help="Rebuild the CSV and manifest from stored records")
    out.add_argument("--data-dir", type=Path, default=Path("data"))

    args = parser.parse_args(argv)
    if args.command == "export":
        print(f"{export(args.data_dir)} records exported")
        return 0

    counties = json.loads(args.counties.read_text(encoding="utf-8"))
    counties = [c for c in counties if c.get("enabled", True)]
    if args.county:
        counties = [c for c in counties if c["county_id"] in args.county]
    today = datetime.now(ZoneInfo("America/New_York")).date()
    summary = collect(
        args.data_dir,
        counties,
        CivilView(delay=args.delay),
        today,
        refresh_days=args.refresh_days,
        include_closed=not args.skip_closed,
    )
    total = export(args.data_dir, summary)
    print(f"{total} records; {summary['details_fetched']} details fetched; {summary['records_written']} written")
    if summary["detail_failures"]:
        print(f"{len(summary['detail_failures'])} detail pages unavailable", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
