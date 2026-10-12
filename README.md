# njss

Daily capture of New Jersey sheriff foreclosure sale notices from [CivilView](https://salesweb.civilview.com/), the listing site that 17 of New Jersey's 21 county sheriffs use.

Counties: Atlantic, Bergen, Burlington, Camden, Cape May, Cumberland, Essex, Gloucester, Hudson, Hunterdon, Middlesex, Monmouth, Morris, Ocean, Passaic, Salem, and Union. Ocean County's listing has been empty since its last update on February 27, 2026.

## Output

- `data/sales/<county>/<sheriff number>_<address>.json`: one file per property, with the sheriff number, court docket number, sale date, parties, address, attorney, parcel, judgment and upset amounts, the full sheriff's notice, and the sale's status history.
- `data/njss_sales.csv`: every record in one table.
- `data/manifest.json`: record counts by county and a summary of the latest run.
- `data/state.json`: when each record's detail page was last checked.

Each record keeps the county's original labels and values under `fields`, so nothing is lost when a county labels a field differently. The normalized fields are:

| Field | County labels it comes from |
| --- | --- |
| `judgment_amount` | Approx. Judgment, Approximate Judgment, Approx Judgment, Judgment |
| `upset_amount` | Approx. Upset, Upset Amount, Good Faith Upset, Minimum Bid |
| `address` | Address, Property Address |
| `description` | Description, Property Details |

`extracted` holds facts read from the notice text: upset price, judgment amount, occupancy, block, and lot. These are best effort reads of free text. The labeled fields are more reliable where both exist, and the two can disagree; the notice for F-26000352 states a judgment of $228,896.26 while its Approximate Judgment field reads $233,375.52.

## How records are keyed

A sheriff's writ can cover several parcels, so the sheriff number alone is not unique; F-26001246 in Gloucester covers four properties. CivilView's internal PropertyId is reassigned whenever the site reloads its data, so it is used only to fetch pages. Each file is keyed by sheriff number and address.

## Updates

The collector reads each county's open listing and its sold and cancelled listing every day. It fetches a sale's detail page when the sale is new, when its listing row changes, or when it leaves the open list. Open sales are also rechecked weekly. A sale that drops off both lists keeps its last record, marked `on_open_list: false` with the date it left.

CivilView's sold and cancelled listing returns only each county's 250 most recent sales, so history before the first run is limited to that window.

## Local use

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
.venv\Scripts\njss collect --county 19
.venv\Scripts\python -m pytest -q
```

`--county` takes a CivilView county ID from `config/counties.json` and may be repeated. Without it, every county runs. Requests are spaced 0.75 seconds apart.

## Source

Every listing is published by the county sheriff's office as public notice of the sale. Most sheriff pages state that its information "is only intended to be general summary information to the public" and that the office "does not warrant the accuracy, completeness, or timeliness of this information." Check the sheriff's office before relying on a sale date or amount.
