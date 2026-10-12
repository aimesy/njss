import json
from datetime import date
from pathlib import Path

from njss.collect import collect, export, slug

FIXTURES = Path(__file__).parent / "fixtures"
GLOUCESTER = [{"county_id": 19, "name": "Gloucester County, NJ"}]


class FakeClient:
    def __init__(self):
        self.listing = (FIXTURES / "search_gloucester.html").read_text(encoding="utf-8")
        self.detail_html = (FIXTURES / "detail_gloucester.html").read_text(encoding="utf-8")
        self.detail_calls = 0

    def open_listing(self, county_id):
        return self.listing

    def closed_listing(self):
        return "<html><body>No search results found.</body></html>"

    def detail(self, property_id):
        self.detail_calls += 1
        return self.detail_html


class ReloadingClient(FakeClient):
    """Reassigns every PropertyId after 40 detail pages, as CivilView does when it reloads."""

    def __init__(self):
        super().__init__()
        self.original = self.listing
        self.reloaded = False
        self.listing_calls = 0

    def open_listing(self, county_id):
        self.listing_calls += 1
        return self.listing

    def detail(self, property_id):
        self.detail_calls += 1
        if self.detail_calls == 40 and not self.reloaded:
            self.reloaded = True
            self.listing = self.original.replace("PropertyId=21868", "PropertyId=21869")
        if self.reloaded and str(property_id).startswith("21868"):
            return "<html><body>Sales Web - Foreclosure Sales Listing</body></html>"
        return self.detail_html


def test_reassigned_ids_mid_run_trigger_one_reload(tmp_path):
    client = ReloadingClient()
    summary = collect(tmp_path, GLOUCESTER, client, date(2026, 10, 12), reload_interval=0, log=lambda *_: None)
    assert summary["detail_failures"] == []
    assert summary["records_written"] == 139
    assert summary["counties"]["Gloucester County, NJ"]["listing_reloads"] == 1
    assert client.listing_calls == 2


def test_second_run_fetches_and_writes_nothing(tmp_path):
    client = FakeClient()
    first = collect(tmp_path, GLOUCESTER, client, date(2026, 10, 12), log=lambda *_: None)
    assert first["details_fetched"] == 139
    assert first["records_written"] == 139
    client.detail_calls = 0
    second = collect(tmp_path, GLOUCESTER, client, date(2026, 10, 13), log=lambda *_: None)
    assert client.detail_calls == 0
    assert second["records_written"] == 0


def test_reassigned_property_ids_do_not_duplicate_records(tmp_path):
    client = FakeClient()
    collect(tmp_path, GLOUCESTER, client, date(2026, 10, 12), log=lambda *_: None)
    client.listing = client.listing.replace("PropertyId=21868", "PropertyId=21869")
    client.detail_calls = 0
    second = collect(tmp_path, GLOUCESTER, client, date(2026, 10, 13), log=lambda *_: None)
    assert client.detail_calls == 0
    assert second["records_written"] == 0
    assert len(list((tmp_path / "sales" / "gloucester").glob("*.json"))) == 139


def test_open_details_refresh_after_window(tmp_path):
    client = FakeClient()
    collect(tmp_path, GLOUCESTER, client, date(2026, 10, 12), refresh_days=7, log=lambda *_: None)
    client.detail_calls = 0
    collect(tmp_path, GLOUCESTER, client, date(2026, 10, 19), refresh_days=7, log=lambda *_: None)
    assert client.detail_calls == 139


def test_sale_leaving_the_lists_is_marked(tmp_path):
    client = FakeClient()
    collect(tmp_path, GLOUCESTER, client, date(2026, 10, 12), log=lambda *_: None)
    client.listing = "<html><body>No search results found.</body></html>"
    collect(tmp_path, GLOUCESTER, client, date(2026, 10, 13), log=lambda *_: None)
    path = tmp_path / "sales" / "gloucester" / "F-26000352_120-williams-avenue-deptford-nj-08096.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["on_open_list"] is False
    assert record["left_open_list"] == "2026-10-13"
    assert record["first_seen"] == "2026-10-12"


def test_export_writes_csv_and_manifest(tmp_path):
    collect(tmp_path, GLOUCESTER, FakeClient(), date(2026, 10, 12), log=lambda *_: None)
    assert export(tmp_path) == 139
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["counties"]["Gloucester County, NJ"] == {"records": 139, "open": 139}
    header = (tmp_path / "njss_sales.csv").read_text(encoding="utf-8").splitlines()[0]
    assert header.startswith("county,sheriff_number,court_case_number")


def test_slug():
    assert slug("Cape May County, NJ") == "cape-may"
    assert slug("Gloucester County, NJ") == "gloucester"
