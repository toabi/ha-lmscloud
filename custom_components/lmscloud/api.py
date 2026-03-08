"""API client for LMSCloud/Koha."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import logging
import re
from typing import Any
from zoneinfo import ZoneInfo

from aiohttp import ClientError, ClientResponse, ClientSession
from yarl import URL

_LOGGER = logging.getLogger(__name__)

_LOGIN_PATH = "/cgi-bin/koha/opac-user.pl"
_FEES_PATH = "/cgi-bin/koha/opac-account.pl"
_LOGIN_CONTEXT = "opac"

_LOGIN_ERROR_MARKERS = (
    "wrong login or password",
    "wrong username or password",
    "invalid username or password",
    "falsches login oder ein falsches passwort",
    "ungueltig",
    "ung\u00fcltig",
)

_CHECKOUT_COUNT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r'(?is)id="opac-user-checkouts-tab"[^>]*>\s*[^<]*\((\d+)\)'),
    re.compile(r'(?is)<caption>\s*(\d+)\s+[^<]*ausgeliehen[^<]*</caption>'),
    re.compile(r"(?i)ausgeliehen\s*\((\d+)\)"),
    re.compile(r"(?i)checkouts?\s*\((\d+)\)"),
)

_OVERDUE_COUNT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r'(?is)id="opac-user-overdues-tab"[^>]*>\s*[^<]*\((\d+)\)'),
    re.compile(r"(?i)\u00fcberf\u00e4llig(?:e|en)?\s*\((\d+)\)"),
    re.compile(r"(?i)overdues?\s*\((\d+)\)"),
)

_HOLDS_READY_COUNT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)abholbereit\s*\((\d+)\)"),
    re.compile(r"(?i)bereit(?:\s+zur\s+abholung)?\s*\((\d+)\)"),
    re.compile(r"(?i)ready(?:\s+for\s+pickup)?\s*\((\d+)\)"),
    re.compile(r"(?i)waiting\s*\((\d+)\)"),
)

_DUE_DATE_DATA_ORDER_PATTERN = re.compile(
    r'(?is)<td[^>]*class="[^"]*date_due[^"]*"[^>]*data-order="([^"]+)"'
)
_DUE_DATE_TEXT_PATTERN = re.compile(r"(?i)\b(\d{2}\.\d{2}\.\d{4})\b")
_TITLE_PATTERN = re.compile(
    r'(?is)<td[^>]*class="[^"]*\btitle\b[^"]*"[^>]*>.*?'
    r'<span[^>]*class="[^"]*\bbiblio-title\b[^"]*"[^>]*>(.*?)</span>'
)
_DATE_DUE_CELL_PATTERN = re.compile(
    r'(?is)<td[^>]*class="[^"]*\bdate_due\b[^"]*"[^>]*data-order="([^"]+)"[^>]*>.*?</td>'
)
_RENEW_CELL_PATTERN = re.compile(
    r'(?is)<td[^>]*class="[^"]*\brenew\b[^"]*"[^>]*>(.*?)</td>'
)
_NO_RENEWAL_BEFORE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)keine\s+verl\u00e4ngerung\s+vor\s+(\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2})"),
    re.compile(r"(?i)no\s+renewal\s+before\s+(\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2})"),
)
_RENEWALS_REMAINING_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\(\s*(\d+)\s+von\s+(\d+)\s+verl\u00e4ngerungen\s+verbleiben"),
    re.compile(r"(?i)\(\s*(\d+)\s+of\s+(\d+)\s+renewals\s+remaining"),
)

_TABLE_BY_ID_PATTERN_TEMPLATE = r'(?is)<table[^>]*id="{table_id}"[^>]*>.*?<tbody>(.*?)</tbody>'
_ROW_PATTERN = re.compile(r"(?is)<tr\b.*?</tr>")
_CELL_PATTERN = re.compile(r"(?is)<t[dh]\b[^>]*>(.*?)</t[dh]>")

_FEES_NO_BALANCE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)keine\s+offenen\s+geb\u00fchren"),
    re.compile(r"(?i)keine\s+geb\u00fchren"),
    re.compile(r"(?i)no\s+outstanding\s+(?:charges|fees|fines)"),
    re.compile(r"(?i)no\s+(?:fees|fines)\s+due"),
)

_FEES_TOTAL_SUM_PATTERN = re.compile(
    r'(?is)<table[^>]*id="finestable"[^>]*>.*?<tfoot>.*?'
    r'<td[^>]*class="[^"]*\bsum\b[^"]*"[^>]*>\s*([+-]?\d{1,9}(?:[.,]\d{2})?)\s*</td>'
)

_FEES_BALANCE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?is)(?:offene\s+geb\u00fchren|geb\u00fchren|kontostand|saldo|balance|outstanding)"
        r"\D{0,40}(-?\d{1,6}(?:[.,]\d{2})?)\s*(?:€|eur)?"
    ),
    re.compile(
        r"(?is)(-?\d{1,6}(?:[.,]\d{2})?)\s*(?:€|eur)\D{0,40}"
        r"(?:geb\u00fchren|kontostand|saldo|balance|outstanding)"
    ),
)


class LMSCloudApiError(Exception):
    """Base exception for LMSCloud API failures."""


class LMSCloudAuthError(LMSCloudApiError):
    """Authentication or authorization failure."""


class LMSCloudConnectionError(LMSCloudApiError):
    """Connection-level failure."""


def normalize_base_url(base_domain: str) -> URL:
    """Normalize a user supplied base domain to the API base URL."""
    raw_value = base_domain.strip()
    if not raw_value:
        raise ValueError("Base domain must not be empty")

    if "://" not in raw_value:
        raw_value = f"https://{raw_value}"

    base_url = URL(raw_value)
    if not base_url.host:
        raise ValueError("Base domain must include a valid host")

    path = base_url.path.rstrip("/")
    if not path:
        path = "/api/v1"

    return base_url.with_path(path).with_query(None).with_fragment(None)


class LMSCloudApiClient:
    """Client for LMSCloud cookie-based account scraping."""

    def __init__(
        self,
        session: ClientSession,
        base_domain: str,
        username: str,
        password: str,
        time_zone: str,
    ) -> None:
        """Initialize the client."""
        self._session = session
        self._api_base_url = normalize_base_url(base_domain)
        self._site_base_url = self._api_base_url.with_path("/")
        self._username = username
        self._password = password
        self._time_zone = ZoneInfo(time_zone)
        self._login_lock = asyncio.Lock()
        self._cookie_authenticated = False

    async def validate_user(self) -> None:
        """Validate user credentials by performing OPAC cookie login."""
        await self._ensure_cookie_authenticated(force=True)

    async def get_account_snapshot(self) -> dict[str, Any]:
        """Return account metrics scraped from OPAC pages."""
        account_html = await self._get_authenticated_page(_LOGIN_PATH)

        due_dates = self._extract_due_dates(account_html)
        borrowed_items = self._extract_borrowed_items(account_html)
        extension_details = self._extract_extension_details(account_html)
        borrowed_count = self._extract_count(account_html, _CHECKOUT_COUNT_PATTERNS)
        if borrowed_count is None:
            borrowed_count = self._count_table_rows(account_html, "checkoutst")
        if borrowed_count is None and due_dates:
            borrowed_count = len(due_dates)
        if borrowed_count is None:
            raise LMSCloudApiError("Unable to determine borrowed books count from OPAC page")

        overdue_count = self._extract_count(account_html, _OVERDUE_COUNT_PATTERNS)
        if overdue_count is None:
            overdue_count = self._count_overdue_due_dates(due_dates)

        next_due_date = min(due_dates) if due_dates else None
        next_extension_possible = self._get_next_extension_possible(extension_details)
        holds_ready_count = self._extract_holds_ready_count(account_html)

        fees_html = await self._get_authenticated_page(_FEES_PATH)
        fees_balance = self._extract_fees_balance(fees_html)

        return {
            "borrowed_count": borrowed_count,
            "borrowed_items": borrowed_items,
            "overdue_count": overdue_count if overdue_count is not None else 0,
            "next_due_date": next_due_date,
            "next_extension_possible": next_extension_possible,
            "next_extension_items": extension_details,
            "holds_ready_count": holds_ready_count,
            "fees_balance": fees_balance,
        }

    async def get_borrowed_count(self) -> int:
        """Backward-compatible borrowed count accessor."""
        snapshot = await self.get_account_snapshot()
        return int(snapshot["borrowed_count"])

    async def _get_authenticated_page(self, path: str) -> str:
        """Fetch page and re-login once if session expired."""
        await self._ensure_cookie_authenticated()
        html = await self._fetch_page(path)
        if self._is_logged_in(html):
            return html

        self._cookie_authenticated = False
        await self._ensure_cookie_authenticated(force=True)
        html = await self._fetch_page(path)
        if self._is_logged_in(html):
            return html

        raise LMSCloudAuthError("Session expired and re-login failed")

    async def _ensure_cookie_authenticated(self, force: bool = False) -> None:
        """Ensure we have a valid OPAC session cookie."""
        if self._cookie_authenticated and not force:
            return

        async with self._login_lock:
            if self._cookie_authenticated and not force:
                return
            await self._perform_cookie_login()
            self._cookie_authenticated = True

    async def _perform_cookie_login(self) -> None:
        """Login against OPAC and establish session cookie."""
        login_url = self._site_base_url.with_path(_LOGIN_PATH)
        form_data = {
            "userid": self._username,
            "password": self._password,
            "koha_login_context": _LOGIN_CONTEXT,
        }

        try:
            preflight_response = await self._session.get(login_url)
            async with preflight_response:
                preflight_body = await preflight_response.text()
                self._debug_log_response(preflight_response, preflight_body)

            response = await self._session.post(
                login_url,
                data=form_data,
                headers={"Referer": str(login_url)},
                allow_redirects=True,
            )
        except (ClientError, TimeoutError) as err:
            raise LMSCloudConnectionError("Unable to reach LMSCloud OPAC login") from err

        async with response:
            login_html = await response.text()
            self._debug_log_response(response, login_html)

        if self._looks_like_login_error(login_html):
            raise LMSCloudAuthError("Invalid OPAC credentials")

        if not self._is_logged_in(login_html):
            # Some instances redirect back to login page on POST even for edge cases.
            account_html = await self._fetch_page(_LOGIN_PATH)
            if not self._is_logged_in(account_html):
                raise LMSCloudAuthError("Cookie-based login did not create an authenticated session")

    async def _fetch_page(self, path: str) -> str:
        """Fetch a page relative to site root and return HTML."""
        url = self._site_base_url.with_path(path)
        try:
            response = await self._session.get(url)
        except (ClientError, TimeoutError) as err:
            raise LMSCloudConnectionError(f"Unable to fetch LMSCloud page {path}") from err

        async with response:
            body = await response.text()
            self._debug_log_response(response, body)
            return body

    def _is_logged_in(self, html: str) -> bool:
        """Return True if HTML indicates an authenticated OPAC session."""
        return "const is_logged_in = true" in html.lower()

    def _looks_like_login_error(self, html: str) -> bool:
        """Return True if HTML includes a known login failure message."""
        normalized = html.lower()
        return any(marker in normalized for marker in _LOGIN_ERROR_MARKERS)

    def _extract_count(
        self, html: str, patterns: tuple[re.Pattern[str], ...]
    ) -> int | None:
        """Extract the first matching numeric count from HTML."""
        for pattern in patterns:
            match = pattern.search(html)
            if not match:
                continue
            try:
                return int(match.group(1))
            except (TypeError, ValueError):
                continue
        return None

    def _extract_due_dates(self, html: str) -> list[datetime]:
        """Extract due dates from checkout table."""
        due_dates: list[datetime] = []
        for raw_value in _DUE_DATE_DATA_ORDER_PATTERN.findall(html):
            parsed = self._parse_due_datetime(raw_value)
            if parsed is not None:
                due_dates.append(parsed)

        if due_dates:
            return due_dates

        checkout_table = self._extract_table_tbody(html, "checkoutst")
        if checkout_table:
            for raw_date in _DUE_DATE_TEXT_PATTERN.findall(checkout_table):
                parsed = self._parse_due_datetime(raw_date)
                if parsed is not None:
                    due_dates.append(parsed)
        return due_dates

    def _extract_holds_ready_count(self, html: str) -> int:
        """Extract number of holds ready for pickup from OPAC page."""
        tab_value = self._extract_count(html, _HOLDS_READY_COUNT_PATTERNS)
        if tab_value is not None:
            return tab_value

        holds_table = self._extract_table_tbody(html, "holdst")
        if not holds_table:
            return 0

        ready_count = 0
        for row in _ROW_PATTERN.findall(holds_table):
            row_text = self._strip_tags(row).lower()
            if (
                "abholbereit" in row_text
                or "bereit zur abholung" in row_text
                or "ready for pickup" in row_text
                or "waiting" in row_text
            ):
                ready_count += 1
        return ready_count

    def _extract_extension_details(self, html: str) -> list[dict[str, Any]]:
        """Extract renewal timing details per checkout row."""
        tbody = self._extract_table_tbody(html, "checkoutst")
        if not tbody:
            return []

        details: list[dict[str, Any]] = []
        for row in _ROW_PATTERN.findall(tbody):
            renew_cell_match = _RENEW_CELL_PATTERN.search(row)
            if not renew_cell_match:
                continue
            renew_cell_html = renew_cell_match.group(1)
            renew_text = self._strip_tags(renew_cell_html)
            extension_dt = self._extract_no_renewal_before(renew_text)
            if extension_dt is None:
                continue

            title = self._extract_title_from_row(row)
            due_date = self._extract_due_date_from_row(row)
            renewals_remaining, renewals_total = self._extract_renewals_remaining(renew_text)

            details.append(
                {
                    "title": title,
                    "extension_possible_at": extension_dt.isoformat(),
                    "due_date": due_date.isoformat() if due_date else None,
                    "renewals_remaining": renewals_remaining,
                    "renewals_total": renewals_total,
                    "renewal_message": renew_text,
                }
            )
        return details

    def _extract_borrowed_items(self, html: str) -> list[dict[str, Any]]:
        """Extract borrowed book details from checkout table."""
        tbody = self._extract_table_tbody(html, "checkoutst")
        if not tbody:
            return []

        items: list[dict[str, Any]] = []
        for row in _ROW_PATTERN.findall(tbody):
            title = self._extract_title_from_row(row)
            due_date = self._extract_due_date_from_row(row)

            renew_cell_match = _RENEW_CELL_PATTERN.search(row)
            renewal_message = self._strip_tags(renew_cell_match.group(1)) if renew_cell_match else None
            extension_dt = self._extract_no_renewal_before(renewal_message or "")
            renewals_remaining, renewals_total = self._extract_renewals_remaining(renewal_message or "")

            items.append(
                {
                    "title": title,
                    "due_date": due_date.isoformat() if due_date else None,
                    "extension_possible_at": extension_dt.isoformat() if extension_dt else None,
                    "renewals_remaining": renewals_remaining,
                    "renewals_total": renewals_total,
                    "renewal_message": renewal_message,
                }
            )
        return items

    def _extract_no_renewal_before(self, renew_text: str) -> datetime | None:
        """Extract 'no renewal before' datetime from renewal text."""
        for pattern in _NO_RENEWAL_BEFORE_PATTERNS:
            match = pattern.search(renew_text)
            if not match:
                continue
            return self._parse_due_datetime(match.group(1))
        return None

    def _extract_renewals_remaining(self, renew_text: str) -> tuple[int | None, int | None]:
        """Extract renewal remaining/total counts from renewal text."""
        for pattern in _RENEWALS_REMAINING_PATTERNS:
            match = pattern.search(renew_text)
            if not match:
                continue
            try:
                return int(match.group(1)), int(match.group(2))
            except ValueError:
                return None, None
        return None, None

    def _extract_title_from_row(self, row_html: str) -> str | None:
        """Extract checkout title from row HTML."""
        match = _TITLE_PATTERN.search(row_html)
        if not match:
            return None
        return self._strip_tags(match.group(1))

    def _extract_due_date_from_row(self, row_html: str) -> datetime | None:
        """Extract due date from checkout row."""
        match = _DATE_DUE_CELL_PATTERN.search(row_html)
        if not match:
            return None
        return self._parse_due_datetime(match.group(1))

    def _get_next_extension_possible(self, details: list[dict[str, Any]]) -> datetime | None:
        """Return earliest extension datetime from parsed details."""
        candidates: list[datetime] = []
        for detail in details:
            value = detail.get("extension_possible_at")
            if not isinstance(value, str):
                continue
            parsed = self._parse_iso_datetime(value)
            if parsed is not None:
                candidates.append(parsed)
        return min(candidates) if candidates else None

    def _extract_fees_balance(self, html: str) -> float | None:
        """Extract current fees balance from account page."""
        table_sum = self._extract_fees_sum_from_table(html)
        if table_sum is not None:
            return table_sum

        row_sum = self._extract_fees_sum_from_rows(html)
        if row_sum is not None:
            return row_sum

        for no_balance_pattern in _FEES_NO_BALANCE_PATTERNS:
            if no_balance_pattern.search(html):
                return 0.0

        for pattern in _FEES_BALANCE_PATTERNS:
            match = pattern.search(html)
            if not match:
                continue
            parsed = self._parse_decimal(match.group(1))
            if parsed is not None:
                return parsed
        return None

    def _extract_fees_sum_from_table(self, html: str) -> float | None:
        """Extract fees balance from finestable tfoot sum cell."""
        match = _FEES_TOTAL_SUM_PATTERN.search(html)
        if not match:
            return None
        return self._parse_decimal(match.group(1))

    def _extract_fees_sum_from_rows(self, html: str) -> float | None:
        """Compute fees balance by summing 'Offener Betrag' values in finestable rows."""
        tbody = self._extract_table_tbody(html, "finestable")
        if not tbody:
            return None

        total = 0.0
        found_any = False
        for row in _ROW_PATTERN.findall(tbody):
            cells = _CELL_PATTERN.findall(row)
            if len(cells) < 7:
                continue

            outstanding_cell_html = cells[6]
            outstanding_value = self._parse_decimal(self._strip_tags(outstanding_cell_html))
            if outstanding_value is None:
                continue

            found_any = True
            cell_html_lower = outstanding_cell_html.lower()
            if "credit" in cell_html_lower:
                total -= outstanding_value
            else:
                total += outstanding_value

        if not found_any:
            return None
        return total

    def _count_overdue_due_dates(self, due_dates: list[datetime]) -> int:
        """Count due dates that are before today."""
        today_utc = datetime.now(tz=UTC).date()
        return sum(1 for due_date in due_dates if due_date.date() < today_utc)

    def _count_table_rows(self, html: str, table_id: str) -> int | None:
        """Count rows in table body for a given table id."""
        tbody = self._extract_table_tbody(html, table_id)
        if tbody is None:
            return None
        return len(_ROW_PATTERN.findall(tbody))

    def _extract_table_tbody(self, html: str, table_id: str) -> str | None:
        """Return table body HTML by table id."""
        pattern = re.compile(
            _TABLE_BY_ID_PATTERN_TEMPLATE.format(table_id=re.escape(table_id)),
            re.IGNORECASE | re.DOTALL,
        )
        match = pattern.search(html)
        if not match:
            return None
        return match.group(1)

    def _parse_due_datetime(self, value: str) -> datetime | None:
        """Parse due datetime from known OPAC formats."""
        try:
            if re.match(r"^\d{4}-\d{2}-\d{2} ", value):
                parsed = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
            elif re.match(r"^\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}$", value):
                parsed = datetime.strptime(value, "%d.%m.%Y %H:%M")
            elif re.match(r"^\d{2}\.\d{2}\.\d{4}$", value):
                parsed = datetime.strptime(value, "%d.%m.%Y")
            else:
                return None
        except ValueError:
            return None
        local_dt = parsed.replace(tzinfo=self._time_zone)
        return local_dt.astimezone(UTC)

    def _parse_iso_datetime(self, value: str) -> datetime | None:
        """Parse ISO datetime string with UTC fallback."""
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=self._time_zone).astimezone(UTC)
        return parsed.astimezone(UTC)

    def _parse_decimal(self, value: str) -> float | None:
        """Parse decimal value from string."""
        normalized = re.sub(r"\s+", "", value.strip())
        if "," in normalized and "." in normalized:
            if normalized.rfind(",") > normalized.rfind("."):
                # European format, e.g. 1.234,56
                normalized = normalized.replace(".", "").replace(",", ".")
            else:
                # US format, e.g. 1,234.56
                normalized = normalized.replace(",", "")
        elif "," in normalized:
            normalized = normalized.replace(",", ".")
        try:
            return float(normalized)
        except ValueError:
            return None

    def _strip_tags(self, html: str) -> str:
        """Remove HTML tags and normalize whitespace."""
        text = re.sub(r"(?is)<[^>]+>", " ", html)
        return re.sub(r"\s+", " ", text).strip()

    def _debug_log_response(self, response: ClientResponse, body: str) -> None:
        """Log raw HTTP response details in debug level."""
        if not _LOGGER.isEnabledFor(logging.DEBUG):
            return
        _LOGGER.debug(
            "LMSCloud response: %s %s status=%s headers=%s body=%s",
            response.method,
            response.url,
            response.status,
            dict(response.headers),
            body,
        )
