"""Scrapers for Singapore Pools TOTO and 4D public result pages."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import date, datetime

import requests
from bs4 import BeautifulSoup

BASE = "https://www.singaporepools.com.sg"
ARCHIVE = f"{BASE}/DataFileArchive/Lottery/Output"
TOTO_LIST_URL = f"{ARCHIVE}/toto_result_draw_list_en.html"
FOURD_LIST_URL = f"{ARCHIVE}/fourd_result_draw_list_en.html"
TOTO_NEXT_URL = f"{ARCHIVE}/toto_next_draw_estimate_en.html"
TOTO_RESULT_URL = f"{BASE}/en/product/sr/Pages/toto_results.aspx?{{qs}}"
FOURD_RESULT_URL = f"{BASE}/en/product/Pages/4d_results.aspx?{{qs}}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120 Safari/537.36"
    )
}
REQUEST_DELAY_S = 1.0

_session = requests.Session()
_session.headers.update(HEADERS)
_last_request = 0.0


def _get(url: str, retries: int = 3) -> str:
    """Polite GET: at most one request per REQUEST_DELAY_S, with retries."""
    global _last_request
    for attempt in range(1, retries + 1):
        wait = REQUEST_DELAY_S - (time.monotonic() - _last_request)
        if wait > 0:
            time.sleep(wait)
        try:
            _last_request = time.monotonic()
            r = _session.get(url, timeout=30)
            r.raise_for_status()
            return r.text
        except requests.RequestException:
            if attempt == retries:
                raise
            time.sleep(2 * attempt)
    raise RuntimeError("unreachable")


def _parse_date(text: str) -> date:
    # e.g. "Thu, 12 Nov 2026"
    return datetime.strptime(text.strip(), "%a, %d %b %Y").date()


def _money(text: str) -> int | None:
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else None


@dataclass
class DrawRef:
    draw_no: int
    draw_date: date
    querystring: str
    cancelled: bool = False


def _draw_list(url: str) -> list[DrawRef]:
    soup = BeautifulSoup(_get(url), "html.parser")
    refs = []
    for opt in soup.find_all("option"):
        # BeautifulSoup lower-cases attribute names.
        qs = opt.get("querystring")
        if not qs or not opt.get("value"):
            continue
        refs.append(
            DrawRef(
                draw_no=int(opt["value"]),
                draw_date=_parse_date(opt.get_text()),
                querystring=qs,
                cancelled=bool((opt.get("iscancelled") or "").strip()),
            )
        )
    return refs


def toto_draw_list() -> list[DrawRef]:
    return _draw_list(TOTO_LIST_URL)


def fourd_draw_list() -> list[DrawRef]:
    return _draw_list(FOURD_LIST_URL)


@dataclass
class TotoResult:
    draw_no: int
    draw_date: date
    numbers: list[int]
    additional: int
    group1_prize: int | None
    prizes: list[tuple[int, int | None, int | None]] = field(default_factory=list)


def _text(soup, cls) -> str:
    el = soup.find(class_=cls)
    if el is None:
        raise ValueError(f"missing element .{cls}")
    return el.get_text(" ", strip=True)


def fetch_toto(ref: DrawRef) -> TotoResult:
    soup = BeautifulSoup(_get(TOTO_RESULT_URL.format(qs=ref.querystring)), "html.parser")
    block = soup.find(class_="divSingleDraw") or soup
    draw_no = int(re.sub(r"\D", "", _text(block, "drawNumber")))
    if draw_no != ref.draw_no:
        raise ValueError(f"TOTO page returned draw {draw_no}, expected {ref.draw_no}")
    numbers = sorted(int(_text(block, f"win{i}")) for i in range(1, 7))
    prizes = []
    table = block.find(class_="tableWinningShares")
    if table is not None:
        for tr in table.find_all("tr"):
            tds = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
            m = re.match(r"Group\s*(\d)", tds[0]) if len(tds) == 3 else None
            if m:
                prizes.append((int(m.group(1)), _money(tds[1]), _money(tds[2])))
    jp = block.find(class_="jackpotPrize")
    return TotoResult(
        draw_no=draw_no,
        draw_date=_parse_date(_text(block, "drawDate")),
        numbers=numbers,
        additional=int(_text(block, "additional")),
        group1_prize=_money(jp.get_text()) if jp else None,
        prizes=prizes,
    )


@dataclass
class FourDResult:
    draw_no: int
    draw_date: date
    first: str
    second: str
    third: str
    starter: list[str]
    consolation: list[str]


def fetch_fourd(ref: DrawRef) -> FourDResult:
    soup = BeautifulSoup(_get(FOURD_RESULT_URL.format(qs=ref.querystring)), "html.parser")
    draw_no = int(re.sub(r"\D", "", _text(soup, "drawNumber")))
    if draw_no != ref.draw_no:
        raise ValueError(f"4D page returned draw {draw_no}, expected {ref.draw_no}")

    def nums(cls):
        body = soup.find(class_=cls)
        if body is None:
            return []
        return [td.get_text(strip=True) for td in body.find_all("td") if re.fullmatch(r"\d{4}", td.get_text(strip=True))]

    return FourDResult(
        draw_no=draw_no,
        draw_date=_parse_date(_text(soup, "drawDate")),
        first=_text(soup, "tdFirstPrize"),
        second=_text(soup, "tdSecondPrize"),
        third=_text(soup, "tdThirdPrize"),
        starter=nums("tbodyStarterPrizes"),
        consolation=nums("tbodyConsolationPrizes"),
    )


@dataclass
class NextToto:
    draw_date: date
    est_jackpot: int | None
    raw_jackpot: str


def fetch_next_toto() -> NextToto:
    soup = BeautifulSoup(_get(TOTO_NEXT_URL), "html.parser")
    raw_date = _text(soup, "toto-draw-date")  # "Mon, 16 Nov 2026 , 6.30pm"
    d = _parse_date(raw_date.split(",")[0] + "," + raw_date.split(",")[1])
    jackpot_el = soup.find("span")
    raw_jp = jackpot_el.get_text(strip=True) if jackpot_el else ""
    return NextToto(draw_date=d, est_jackpot=_money(raw_jp), raw_jackpot=raw_jp)
