"""HTTP access to salesweb.civilview.com."""

from __future__ import annotations

import sys
import time

import requests

BASE = "https://salesweb.civilview.com"
USER_AGENT = "njss public-record capture (+https://amyc.us; me@amyc.us)"
CLOSED_FORM = {
    "IsOpen": "false",
    "SheriffNumber": "",
    "PropertyStatusDate": "",
    "MonthNumber": "0",
    "PlaintiffTitle": "",
    "DefendantTitle": "",
    "Address": "",
    "CityDesc": "",
}


class CivilView:
    """One polite session per county.

    Detail pages only render after the county's search page sets the session,
    and a session reused across counties can serve the home page instead, so
    each county gets a fresh session.
    """

    def __init__(self, delay: float = 0.75, timeout: float = 60.0, retries: int = 3):
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self.session: requests.Session | None = None
        self.county_id: int | None = None
        self.requests_made = 0

    def _new_session(self) -> requests.Session:
        session = requests.Session()
        session.headers["User-Agent"] = USER_AGENT
        return session

    def _call(self, method: str, url: str, **kwargs) -> str:
        last_error: Exception | None = None
        for attempt in range(self.retries):
            if self.requests_made:
                time.sleep(self.delay)
            self.requests_made += 1
            started = time.monotonic()
            try:
                response = self.session.request(method, url, timeout=self.timeout, **kwargs)
                response.raise_for_status()
                elapsed = time.monotonic() - started
                if elapsed > 10:
                    print(f"  slow response: {elapsed:.0f}s {method} {url}", file=sys.stderr, flush=True)
                return response.text
            except requests.RequestException as error:
                last_error = error
                print(f"  attempt {attempt + 1} failed: {method} {url}: {error}", file=sys.stderr, flush=True)
                time.sleep(self.delay * (attempt + 2) * 2)
        raise RuntimeError(f"{method} {url} failed after {self.retries} attempts") from last_error

    def home(self) -> str:
        self.session = self._new_session()
        return self._call("GET", f"{BASE}/")

    def open_listing(self, county_id: int) -> str:
        self.session = self._new_session()
        self.county_id = county_id
        return self._call("GET", f"{BASE}/Sales/SalesSearch?countyId={county_id}")

    def closed_listing(self) -> str:
        return self._call("POST", f"{BASE}/Sales/SalesSearch", data=CLOSED_FORM)

    def reprime(self) -> None:
        self.open_listing(self.county_id)

    def detail(self, property_id: int) -> str:
        return self._call("GET", f"{BASE}/Sales/SaleDetails?PropertyId={property_id}")
