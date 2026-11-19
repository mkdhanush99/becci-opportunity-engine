"""Content extraction helpers. All page content is treated as untrusted data.

Rules:
* Only visible text is kept; <script>, <style>, <noscript>, <template>, <iframe>, forms are dropped.
* Extraction is deterministic and pattern-based. Values are only recorded when they appear verbatim in
  the source text, and every value is stored together with an evidence snippet.
* Nothing is inferred: if a deadline / salary / vacancy count is not explicitly stated, it stays None.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import io
import re
import unicodedata
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

DROP_TAGS = ["script", "style", "noscript", "template", "iframe", "object", "embed", "svg", "form", "canvas"]

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}


def soup_of(html: str | bytes) -> BeautifulSoup:
    s = BeautifulSoup(html, "lxml")
    for t in s(DROP_TAGS):
        t.decompose()
    return s


def clean_text(s: str | None) -> str:
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = re.sub(r"[\u200b-\u200f\u202a-\u202e\ufeff]", "", s)  # zero-width / bidi control chars
    return re.sub(r"\s+", " ", s).strip()


def visible_text(html: str | bytes) -> str:
    return clean_text(soup_of(html).get_text(" ", strip=True))


def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def title_key(title: str) -> str:
    t = clean_text(title).lower()
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def slugify(s: str, max_len: int = 120) -> str:
    t = title_key(s).replace(" ", "-")
    return t[:max_len].strip("-") or "opportunity"


# ----------------------------------------------------------------------------- dates
_DATE_ISO = re.compile(r"^\s*(\d{4})[./-](\d{1,2})[./-](\d{1,2})")
_DATE_NUM = r"(\d{1,2})[./-](\d{1,2})[./-](\d{4}|\d{2})"
_DATE_TXT = r"(\d{1,2})(?:st|nd|rd|th)?[\s.-]*(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*[\s.,-]*(\d{4})"
_DATE_TXT_US = r"(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*[\s.]+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})"
DATE_ANY = re.compile(f"{_DATE_NUM}|{_DATE_TXT}|{_DATE_TXT_US}", re.I)


def parse_date(s: str) -> dt.date | None:
    """Parse Indian-style dates (day first) or ISO dates (year first). Returns None if ambiguous/invalid."""
    if not s:
        return None
    # 1. Check ISO format (YYYY-MM-DD or YYYY/MM/DD)
    m_iso = _DATE_ISO.match(s)
    if m_iso:
        try:
            return dt.date(int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3)))
        except ValueError:
            return None

    # 2. Check general date patterns (day first for Indian portals)
    m = DATE_ANY.search(s)
    if not m:
        return None
    g = m.groups()
    try:
        if g[0]:
            d, mo, y = int(g[0]), int(g[1]), int(g[2])
            if y < 100:
                y += 2000
        elif g[3]:
            d, mo, y = int(g[3]), MONTHS[g[4][:3].lower()], int(g[5])
        else:
            mo, d, y = MONTHS[g[6][:3].lower()], int(g[7]), int(g[8])
        return dt.date(y, mo, d)
    except (ValueError, KeyError):
        return None


@dataclass
class Claim:
    field: str
    value: str
    snippet: str


def snippet_around(text: str, start: int, end: int, pad: int = 90) -> str:
    a, b = max(0, start - pad), min(len(text), end + pad)
    return ("…" if a > 0 else "") + text[a:b].strip() + ("…" if b < len(text) else "")


DEADLINE_PATTERNS = [
    re.compile(r"last\s+date\s*(?:&|and)?\s*(?:time)?\s*(?:of|for)?\s*(?:submission|receipt|registration|"
               r"applying|apply|online\s+application)?[^.\n]{0,60}?" + f"({DATE_ANY.pattern})", re.I),
    re.compile(r"(?:closing|due)\s+date[^.\n]{0,40}?" + f"({DATE_ANY.pattern})", re.I),
    re.compile(r"(?:apply|applications?)\s+(?:on\s*line\s+)?(?:on\s+or\s+)?before\s+" + f"({DATE_ANY.pattern})", re.I),
    re.compile(r"\bto\s*:?\s*" + f"({DATE_ANY.pattern})" + r"[^.\n]{0,20}(?:last\s+date)", re.I),
]
OPENING_PATTERNS = [
    re.compile(r"(?:submission\s+of\s+online\s+application|online\s+applications?|registration)\s+"
               r"(?:will\s+)?(?:start|commence|open)s?\s*(?:from|on)?\s*:?\s*" + f"({DATE_ANY.pattern})", re.I),
    re.compile(r"(?:submission\s+of\s+online\s+application|application)\s+from\s*:?\s*" + f"({DATE_ANY.pattern})", re.I),
    re.compile(r"(?:opening|starting|start)\s+date[^.\n]{0,40}?" + f"({DATE_ANY.pattern})", re.I),
]


def find_dated_claim(text: str, patterns, field_name: str) -> Claim | None:
    for pat in patterns:
        m = pat.search(text)
        if m:
            raw = m.group(1)
            d = parse_date(raw)
            if d:
                return Claim(field_name, d.isoformat(), snippet_around(text, m.start(), m.end()))
    return None


REF_PATTERNS = [
    re.compile(r"(?:notification|notfn|notifn|advt|advertisement|employment notice|tender)\.?\s*(?:no|number)\.?\s*[:.]?\s*"
               r"([A-Z0-9][A-Z0-9/\-.()]{1,40}\d)", re.I),
]


def find_reference(text: str) -> Claim | None:
    for pat in REF_PATTERNS:
        m = pat.search(text)
        if m:
            ref = m.group(1).strip(" .,-")
            return Claim("reference_number", ref.upper(), snippet_around(text, m.start(), m.end()))
    return None


VACANCY_PATTERN = re.compile(r"(?:total\s+(?:no\.?\s+of\s+)?(?:vacancies|posts)|no\.?\s+of\s+(?:vacancies|posts))"
                             r"\s*[:\-]?\s*(\d{1,6})\b", re.I)


def find_vacancies(text: str) -> Claim | None:
    m = VACANCY_PATTERN.search(text)
    if m:
        return Claim("positions", m.group(1), snippet_around(text, m.start(), m.end()))
    return None


def value_in_text(value: str, text: str) -> bool:
    """Evidence check: is this extracted value present (normalised) in the source text?"""
    if not value:
        return False
    v = title_key(value)
    return bool(v) and v in title_key(text)


# ----------------------------------------------------------------------------- PDF
def pdf_text(data: bytes, max_pages: int = 6) -> str:
    """Extract text from a public PDF (first pages only). Returns '' if not parseable."""
    try:
        from pypdf import PdfReader
        r = PdfReader(io.BytesIO(data))
        if r.is_encrypted:
            return ""
        out = []
        for p in r.pages[:max_pages]:
            out.append(p.extract_text() or "")
        return clean_text("\n".join(out))
    except Exception:
        return ""


@dataclass
class ExtractedItem:
    """Output of a source parser: one candidate opportunity with raw values + evidence."""
    external_key: str
    title: str
    original_url: str
    raw_text: str
    fields: dict = field(default_factory=dict)  # normalised-field-name -> value (str / iso date)
    claims: list[Claim] = field(default_factory=list)
    documents: list[dict] = field(default_factory=list)  # [{title, url}]
    related_notices: list[dict] = field(default_factory=list)
    application_url: str | None = None
    subcategory: str | None = None
    skip_reason: str | None = None  # set when the item is seen but not an opportunity
