"""Collect sheriff sale records and keep one JSON file per sale."""

from __future__ import annotations

import csv
import json
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from njss.client import BASE, CivilView
from njss.parse import parse_detail, parse_listing

LISTING_KEYS = ("listing_status", "sale_date", "plaintiff", "defendant", "address")
CSV_COLUMNS = [
    "county",
    "sheriff_number",
    "court_case_number",
    "on_open_list",
    "current_status",
    "listing_status",
    "sale_date",
    "plaintiff",
    "defendant",
    "address",
    "parcel",
    "judgment_amount",
    "upset_amount",
    "attorney",
    "attorney_phone",
    "occupancy",
    "first_seen",
    "source_listing",
]


def slug(name: str) -> str:
    name = re.sub(r"\s+County,?\s*[A-Z]{2}$", "", name)
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def file_key(sheriff_number: str, address: str) -> str:
    """One file per property.

    A single writ can cover several parcels, so the sheriff number alone is not
    unique. CivilView's PropertyId is reassigned whenever the site reloads its
    data, so it is used only to fetch pages, never as a key.
    """
    writ = re.sub(r"[^A-Za-z0-9\-]+", "-", sheriff_number).strip("-") or "unnumbered"
    place = re.sub(r"[^a-z0-9]+", "-", (address or "").lower()).strip("-")[:48].strip("-")
    return f"{writ}_{place or 'no-address'}"


def read_json(path: Path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def write_json(path: Path, value) -> bool:
    """Write only when the content changed, so Git sees real changes only."""
    text = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def listing_values(row: dict) -> dict:
    return {key: row.get(key) for key in LISTING_KEYS}


def needs_detail(
    stored: dict | None, row: dict, on_open: bool, checked: str | None, today: date, refresh_days: int
) -> bool:
    if stored is None or "status_history" not in stored:
        return True
    if stored.get("listing") != listing_values(row):
        return True
    if stored.get("on_open_list") != on_open:
        return True
    if not on_open:
        return False
    if checked is None:
        return True
    return date.fromisoformat(checked) <= today - timedelta(days=refresh_days)


def collect(
    data_dir: Path,
    counties: list[dict],
    client: CivilView,
    today: date,
    refresh_days: int = 7,
    include_closed: bool = True,
    log=print,
) -> dict:
    state_path = data_dir / "state.json"
    state = read_json(state_path, {"detail_checked": {}})
    summary = {"counties": {}, "records_written": 0, "details_fetched": 0, "detail_failures": []}
    for county in counties:
        cid, name = county["county_id"], county["name"]
        folder = data_dir / "sales" / slug(name)
        listing = parse_listing(client.open_listing(cid))
        seen = {}
        for row in listing["rows"]:
            seen[file_key(row["sheriff_number"], row["address"])] = (row, True)
        if include_closed:
            for row in parse_listing(client.closed_listing())["rows"]:
                seen.setdefault(file_key(row["sheriff_number"], row["address"]), (row, False))
        written = fetched = 0
        for key, (row, on_open) in seen.items():
            path = folder / f"{key}.json"
            stored = read_json(path, None)
            state_key = f"{cid}/{key}"
            if not needs_detail(stored, row, on_open, state["detail_checked"].get(state_key), today, refresh_days):
                continue
            detail = parse_detail(client.detail(row["property_id"]))
            if detail is None:
                client.reprime()
                detail = parse_detail(client.detail(row["property_id"]))
            fetched += 1
            if fetched % 50 == 0:
                log(f"  {name}: {fetched} details fetched")
                # Save progress so an interrupted run does not refetch what it already has.
                write_json(state_path, state)
            if detail is None:
                summary["detail_failures"].append(state_key)
                log(f"  detail unavailable: {name} {row['sheriff_number']}")
                continue
            record = dict(detail)
            record.update(
                {
                    "listing": listing_values(row),
                    "listing_status": row.get("listing_status"),
                    "sale_date": detail.get("sale_date") or row.get("sale_date"),
                    "county": name,
                    "county_id": cid,
                    "address": row.get("address") or detail.get("address"),
                    "sheriff_number": row["sheriff_number"] or detail.get("sheriff_number"),
                    "on_open_list": on_open,
                    "first_seen": (stored or {}).get("first_seen", today.isoformat()),
                    "source_listing": f"{BASE}/Sales/SalesSearch?countyId={cid}",
                }
            )
            state["detail_checked"][state_key] = today.isoformat()
            if write_json(path, record):
                written += 1
        # A sale that leaves the open list and is past the closed list's
        # 250 row window keeps its last record, marked off the open list.
        for path in sorted(folder.glob("*.json")) if folder.exists() else []:
            if path.stem in seen:
                continue
            stored = read_json(path, {})
            if stored.get("on_open_list"):
                stored["on_open_list"] = False
                stored["left_open_list"] = today.isoformat()
                if write_json(path, stored):
                    written += 1
        summary["counties"][name] = {
            "county_id": cid,
            "open_listed": len(listing["rows"]),
            "tracked": len(seen),
            "details_fetched": fetched,
            "records_written": written,
            "source_last_updated": listing["source_last_updated"],
        }
        summary["records_written"] += written
        summary["details_fetched"] += fetched
        log(f"{name}: {len(listing['rows'])} open, {len(seen)} tracked, {fetched} details, {written} written")
        write_json(state_path, state)
    return summary


def export(data_dir: Path, summary: dict | None = None) -> int:
    records = []
    for path in sorted((data_dir / "sales").glob("*/*.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        record["occupancy"] = (record.get("extracted") or {}).get("occupancy")
        for key in ("judgment_amount", "upset_amount"):
            if record.get(key) is None:
                record[key] = (record.get("extracted") or {}).get(key)
        records.append(record)
    records.sort(key=lambda r: (r["county"], r.get("sale_date") or "", r.get("sheriff_number") or ""))
    out = data_dir / "njss_sales.csv"
    with out.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        writer.writerows(records)
    by_county: dict[str, dict] = {}
    for record in records:
        entry = by_county.setdefault(record["county"], {"records": 0, "open": 0})
        entry["records"] += 1
        entry["open"] += 1 if record.get("on_open_list") else 0
    manifest = {
        "source": BASE,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "records": len(records),
        "open": sum(1 for r in records if r.get("on_open_list")),
        "counties": by_county,
    }
    if summary is not None:
        manifest["last_run"] = summary
    write_json(data_dir / "manifest.json", manifest)
    return len(records)
