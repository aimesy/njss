from pathlib import Path

from njss.parse import parse_counties, parse_detail, parse_listing

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_home_lists_new_jersey_counties():
    counties = parse_counties(fixture("home.html"))
    assert len(counties) == 67
    nj = [c for c in counties if c["state"] == "NJ"]
    assert len(nj) == 17
    assert {"county_id": 19, "name": "Gloucester County, NJ", "state": "NJ"} in nj


def test_listing_reads_columns_by_header():
    listing = parse_listing(fixture("search_gloucester.html"))
    assert len(listing["rows"]) == 139
    assert listing["source_last_updated"] == "10/12/2026 3:50:00 AM"
    assert listing["rows"][0] == {
        "property_id": 2186854802,
        "sheriff_number": "F-26000352",
        "listing_status": "Scheduled",
        "sale_date": "2026-10-14",
        "plaintiff": "FIRST NATIONAL BANK OF AMERICA",
        "defendant": "CHRISTOPHER STONEY & LUCILLA HERNANDEZ, ET ALS",
        "address": "120 WILLIAMS AVENUE DEPTFORD NJ 08096",
    }


def test_listing_without_status_column():
    rows = parse_listing(fixture("search_essex.html"))["rows"]
    assert len(rows) == 191
    assert rows[0]["listing_status"] is None
    assert rows[0]["sheriff_number"] == "F-25000143"
    assert rows[0]["sale_date"] == "2026-10-13"


def test_detail_fields_history_and_notice():
    detail = parse_detail(fixture("detail_gloucester.html"))
    assert detail["sheriff_number"] == "F-26000352"
    assert detail["court_case_number"] == "F-003842-24"
    assert detail["sale_date"] == "2026-10-14"
    assert detail["judgment_amount"] == 233375.52
    assert detail["judgment_amount_label"] == "Approximate Judgment"
    assert detail["parcel"] == "LOT: 8 BLOCK: 187"
    assert detail["attorney"] == "THE KANCHER LAW FIRM, L.L.C."
    assert [h["status"] for h in detail["status_history"]] == [
        "Scheduled",
        "Defendant Adjourned to",
        "Defendant Adjourned to",
        "Bankruptcy Hold",
        "Scheduled",
    ]
    assert detail["current_status"] == "Scheduled"
    assert detail["extracted"]["upset_amount"] == 244857.24
    assert detail["extracted"]["judgment_amount"] == 228896.26
    assert detail["extracted"]["occupancy"] == "OWNER OCCUPIED"
    assert detail["extracted"]["block"] == "187"
    assert detail["extracted"]["lot"] == "8"
    assert "WRIT OF EXECUTION" in detail["description"].upper()


def test_detail_label_variants_map_to_one_field():
    hudson = parse_detail(fixture("detail_hudson.html"))
    assert hudson["upset_amount_label"] == "Good Faith Upset*"
    assert hudson["judgment_amount_label"] == "Judgment"
    cape_may = parse_detail(fixture("detail_capemay.html"))
    assert cape_may["upset_amount_label"] == "Minimum Bid"
    assert cape_may["sale_date"] is not None
    assert cape_may["address"]


def test_detail_returns_none_for_other_pages():
    assert parse_detail(fixture("home.html")) is None
