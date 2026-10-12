"""Parsers for CivilView sheriff sale pages."""

from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup

DETAIL_HREF = re.compile(r"PropertyId=(\d+)")
COUNTY_HREF = re.compile(r"countyId=(\d+)")
MONEY = re.compile(r"\$\s*([\d,]+(?:\.\d{2})?)")
LAST_UPDATED = re.compile(r"last updated:\s*([^)]+)\)", re.IGNORECASE)

# Detail labels differ by county. Each canonical field lists the label
# spellings seen on the live site, after normalize_label().
LABELS = {
    "sheriff_number": ["sheriff"],
    "court_case_number": ["court case"],
    "sale_date": ["sales date", "sale date"],
    "plaintiff": ["plaintiff"],
    "defendant": ["defendant"],
    "address": ["address", "property address"],
    "description": ["description", "property details"],
    "judgment_amount": [
        "approx judgment",
        "approximate judgment",
        "judgment",
    ],
    "upset_amount": [
        "approx upset",
        "upset amount",
        "good faith upset",
        "minimum bid",
    ],
    "attorney": ["attorney"],
    "attorney_phone": ["attorney phone"],
    "attorney_file_number": ["attorney file"],
    "parcel": ["parcel"],
    "priors": ["priors"],
    "deed": ["deed"],
    "deed_address": ["deed address"],
    "property_note": ["property note"],
}
LABEL_TO_FIELD = {label: field for field, labels in LABELS.items() for label in labels}
MONEY_FIELDS = {"judgment_amount", "upset_amount"}


def soup_of(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def clean(text: str | None) -> str:
    return re.sub(r"[ \t\r\f\v]+", " ", text or "").strip()


def normalize_label(label: str) -> str:
    label = label.lower().replace("&colon;", "")
    label = re.sub(r"[:*#.]", "", label)
    return re.sub(r"\s+", " ", label).strip()


def iso_date(value: str | None) -> str | None:
    value = clean(value)
    for fmt in ("%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def money(value: str | None) -> float | None:
    match = MONEY.search(value or "")
    return float(match.group(1).replace(",", "")) if match else None


def parse_counties(html: str) -> list[dict]:
    """Return every jurisdiction linked from the CivilView home page."""
    counties = []
    for link in soup_of(html).select("a[href*='countyId']"):
        match = COUNTY_HREF.search(link["href"])
        name = clean(link.get_text(" "))
        state = name.rsplit(",", 1)[-1].strip() if "," in name else ""
        counties.append({"county_id": int(match.group(1)), "name": name, "state": state})
    return counties


def parse_listing(html: str) -> dict:
    """Parse a county search page into its banner and sale rows.

    Columns differ by county (Essex has no Status column), so cells are read
    by header name rather than position.
    """
    soup = soup_of(html)
    banner = clean(soup.find("table").get_text(" ")) if soup.find("table") else ""
    updated = LAST_UPDATED.search(banner)
    rows = []
    first = soup.select_one("a[href*='SaleDetails']")
    if first is not None:
        table = first.find_parent("table")
        header = [clean(c.get_text(" ")) for c in table.find("tr").find_all(["th", "td"])]
        for tr in table.find_all("tr")[1:]:
            link = tr.select_one("a[href*='SaleDetails']")
            if link is None:
                continue
            cells = [clean(td.get_text(" ")) for td in tr.find_all("td")]
            values = dict(zip(header, cells))
            rows.append(
                {
                    "property_id": int(DETAIL_HREF.search(link["href"]).group(1)),
                    "sheriff_number": values.get("Sheriff #", ""),
                    "listing_status": values.get("Status"),
                    "sale_date": iso_date(values.get("Sales Date")),
                    "plaintiff": values.get("Plaintiff", ""),
                    "defendant": values.get("Defendant", ""),
                    "address": values.get("Address", ""),
                }
            )
    return {"source_last_updated": updated.group(1).strip() if updated else None, "rows": rows}


def description_text(value_div) -> str:
    lines = [clean(line) for line in value_div.get_text("\n").split("\n")]
    return "\n".join(line for line in lines if line)


def parse_detail(html: str) -> dict | None:
    """Parse a sale detail page. Returns None when the site served another page."""
    soup = soup_of(html)
    items = soup.select(".sale-detail-item")
    if not items:
        return None
    heading = soup.find("h1")
    raw_fields = {}
    record: dict = {}
    for item in items:
        label_div = item.select_one(".sale-detail-label")
        value_div = item.select_one(".sale-detail-value")
        if label_div is None or value_div is None:
            continue
        label = clean(label_div.get_text(" ")).rstrip(":").strip()
        value = description_text(value_div)
        raw_fields[label] = value
        field = LABEL_TO_FIELD.get(normalize_label(label))
        if field is None:
            continue
        if field not in ("description", "property_note"):
            value = value.replace("\n", " ")
        if field in MONEY_FIELDS:
            record[field] = money(value)
            record[f"{field}_label"] = label
        elif field == "sale_date":
            record[field] = iso_date(value)
        else:
            record[field] = value or None
    history = []
    table = soup.find("table")
    if table is not None:
        for tr in table.find_all("tr")[1:]:
            cells = [clean(td.get_text(" ")) for td in tr.find_all("td")]
            if len(cells) >= 2 and cells[0]:
                history.append({"status": cells[0], "date": iso_date(cells[1])})
    record["status_history"] = history
    record["current_status"] = history[-1]["status"] if history else None
    record["page_title"] = clean(heading.get_text(" ")) if heading else None
    record["fields"] = raw_fields
    record["extracted"] = extract_from_description(record.get("description") or "")
    return record


def extract_from_description(text: str) -> dict:
    """Pull common facts out of the sheriff's notice text.

    These are best effort reads of free text; the raw notice stays in
    `description`, and the labeled fields win wherever both exist.
    """
    found: dict = {}
    patterns = {
        "upset_amount": r"UPSET PRICE[^$]*(\$\s*[\d,]+(?:\.\d{2})?)",
        "judgment_amount": r"amount of the judgment[^$]*(\$\s*[\d,]+(?:\.\d{2})?)",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            found[key] = money(match.group(1))
    occupancy = re.search(r"OCCUPANCY(?: STATUS)?:\s*([^\n]+)", text, re.IGNORECASE)
    if occupancy:
        found["occupancy"] = clean(occupancy.group(1))
    block = re.search(r"\bBLOCK:?\s*([\w.\-]+)", text, re.IGNORECASE)
    lot = re.search(r"\bLOT:?\s*([\w.\-]+)", text, re.IGNORECASE)
    if block:
        found["block"] = block.group(1).rstrip(".,")
    if lot:
        found["lot"] = lot.group(1).rstrip(".,")
    return found
