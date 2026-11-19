"""AGENT 02 - FUNDING SCOUT: discovers official MSME, OBC, and startup funding/subsidy programmes.

Tested against live public sources:
* nbcfdc_schemes - NBCFDC Individual & Group Loan Schemes (Ministry of Social Justice & Empowerment)
* sidbi_schemes  - SIDBI MSME Loan & Credit Schemes (sitemap & direct scheme pages)
"""
from __future__ import annotations

import re
from app.agents.base import AgentConfig, BaseAgent, ScanContext
from app.models import Source
from app.pipeline.extraction import (
    Claim,
    ExtractedItem,
    clean_text,
    soup_of,
    visible_text,
)
from app.security.urls import safe_link


def nbcfdc_schemes(source: Source, ctx: ScanContext) -> list[ExtractedItem]:
    """Extract official loan schemes from NBCFDC portal."""
    res = ctx.http.get(source.url)
    html = res.text
    ctx.capture(source.url, res.final_url, "http", res.status, visible_text(html))
    s = soup_of(html)

    # Locate scheme links from main or menu
    scheme_urls = []
    for a in s.find_all("a", href=True):
        href = a["href"]
        text = clean_text(a.get_text(" ", strip=True))
        if any(k in href.lower() for k in ["individual-loan-scheme", "group-loan-scheme", "other-schemes"]):
            u = safe_link(href, res.final_url)
            if u and u not in scheme_urls:
                scheme_urls.append(u)

    ctx.step("nbcfdc.scheme_links_found", count=len(scheme_urls))
    items: list[ExtractedItem] = []

    for scheme_url in scheme_urls[:source.config.get("max_subpages", 5)]:
        try:
            page_res = ctx.http.get(scheme_url)
            page_soup = soup_of(page_res.text)
            content_area = page_soup.find("div", class_="region-content") or page_soup.find("article") or page_soup
            title_node = content_area.find(
                lambda tag: tag.name in ["h1", "h2", "h3", "h4"] and "visually-hidden" not in tag.get("class", [])
            )
            title = clean_text(title_node.get_text(" ", strip=True)) if title_node else "NBCFDC Loan Scheme"
            body_text = clean_text(page_soup.get_text(" ", strip=True))
            ctx.capture(scheme_url, page_res.final_url, "http", page_res.status, body_text[:200000])

            fields = {}
            claims = [
                Claim("title", title, title),
                Claim("issuing_organisation", "National Backward Classes Finance & Development Corporation (NBCFDC)",
                      "NBCFDC (A Govt. of India Undertaking)")
            ]

            # Extract eligibility
            elig_m = re.search(r"Eligibility[:\s]+(.*?)(?:Salient Features|Pattern of Finance|Rate of Interest|$)", body_text, re.I)
            if elig_m:
                elig_txt = elig_m.group(1).strip()[:500]
                fields["eligibility"] = elig_txt
                claims.append(Claim("eligibility", elig_txt, elig_m.group(0)[:300]))

            # Extract financial limits
            fin_m = re.search(r"(Maximum loan limit\s*:[^.\n]+|Rate of Interest[^.\n]+)", body_text, re.I)
            if fin_m:
                fin_txt = fin_m.group(0).strip()[:300]
                fields["financial_details"] = fin_txt
                claims.append(Claim("financial_details", fin_txt, fin_m.group(0)[:200]))

            item = ExtractedItem(
                external_key=f"nbcfdc:{scheme_url.rstrip('/').split('/')[-1]}",
                title=title,
                original_url=scheme_url,
                raw_text=body_text[:10000],
                fields=fields,
                claims=claims,
                subcategory="credit_linked_scheme",
            )
            items.append(item)
            ctx.step("nbcfdc.scheme_extracted", title=title, url=scheme_url)
        except Exception as e:
            ctx.step("nbcfdc.scheme_error", url=scheme_url, error=str(e)[:200])

    return items


def sidbi_schemes(source: Source, ctx: ScanContext) -> list[ExtractedItem]:
    """Extract official MSME financing products from SIDBI."""
    res = ctx.http.get(source.url)
    xml_text = res.text
    ctx.capture(source.url, res.final_url, "http", res.status, xml_text[:50000])

    # Find relevant scheme URLs from sitemap
    locs = re.findall(r"<loc>([^<]+)</loc>", xml_text)
    scheme_targets = [
        u for u in locs if any(k in u for k in ["machinery-loan", "project-funding", "green-finance", "prayaas"])
    ]
    ctx.step("sidbi.sitemap_filtered", count=len(scheme_targets))

    items: list[ExtractedItem] = []
    for s_url in scheme_targets[:source.config.get("max_subpages", 4)]:
        try:
            p_res = ctx.http.get(s_url)
            p_soup = soup_of(p_res.text)
            h1 = p_soup.find("h1")
            meta_title = p_soup.find("title")
            raw_title = (h1.get_text(strip=True) if h1 else
                         clean_text(meta_title.get_text(strip=True)) if meta_title else s_url.split("/")[-1])
            title = re.sub(r"-\s*Small Industries Development Bank of India.*", "", raw_title, flags=re.I).strip(" -")
            if not title:
                title = f"SIDBI {s_url.split('/')[-1].replace('-', ' ').title()}"

            body_text = clean_text(p_soup.get_text(" ", strip=True))
            ctx.capture(s_url, p_res.final_url, "http", p_res.status, body_text[:200000])

            fields = {"financial_details": "Direct MSME financial assistance as notified by SIDBI"}
            claims = [
                Claim("title", title, raw_title),
                Claim("issuing_organisation", "Small Industries Development Bank of India (SIDBI)", "SIDBI")
            ]

            item = ExtractedItem(
                external_key=f"sidbi:{s_url.rstrip('/').split('/')[-1]}",
                title=title,
                original_url=s_url,
                raw_text=body_text[:10000],
                fields=fields,
                claims=claims,
                subcategory="msme_support"
            )
            items.append(item)
            ctx.step("sidbi.scheme_extracted", title=title, url=s_url)
        except Exception as e:
            ctx.step("sidbi.scheme_error", url=s_url, error=str(e)[:200])

    return items


class FundingScout(BaseAgent):
    agent_id = "funding_scout"
    name = "Funding Scout"
    description = "Discovers business finance, credit-linked schemes, and government subsidy programmes."
    config = AgentConfig(
        category="funding",
        mandatory_fields=["title", "original_url"],
        subcategories=[
            "government_subsidy",
            "entrepreneurship_grant",
            "credit_linked_scheme",
            "msme_support",
            "startup_funding"
        ]
    )
    parsers = {
        "nbcfdc_schemes": nbcfdc_schemes,
        "sidbi_schemes": sidbi_schemes,
    }
