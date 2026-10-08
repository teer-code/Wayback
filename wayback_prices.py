#!/usr/bin/env python3
"""
wayback_prices.py — extract historical fragrance prices from the Internet Archive.

Starts with Byredo but is brand-agnostic: add entries to BRANDS and it works.

Pipeline:
  1. CDX query   -> list every archived snapshot of the brand's product pages
  2. Fetch       -> download snapshots (cached to disk; re-runs are free)
  3. Parse       -> pull name / size / price out of each snapshot
  4. Emit        -> tidy CSV, one row per (product, size, snapshot date)

Usage:
    python wayback_prices.py byredo --from 2014 --to 2026
    python wayback_prices.py byredo --cdx-only      # just see what's available
    python wayback_prices.py --list

Deliberately polite: 5s between archive.org requests. A full brand takes
a while. Let it run in the background.
"""

import argparse
import csv
import json
import os
import re
import sys
import time
import hashlib
from dataclasses import dataclass, asdict
from pathlib import Path
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

CDX_API = "http://web.archive.org/cdx/search/cdx"
WAYBACK = "http://web.archive.org/web"
CACHE = Path("cache")
OUT = Path("data")

# archive.org rate-limits aggressively. Do not lower this.
DELAY = 5.0
TIMEOUT = 45
RETRIES = 3
CDX_RETRIES = 8  # the index call gates an entire crawl, so be stubborn about it

HEADERS = {
    "User-Agent": "fragrance-price-research/0.1 (academic price-history study)"
}


# --------------------------------------------------------------------------
# Brand configuration
# --------------------------------------------------------------------------

@dataclass
class Brand:
    slug: str
    domain: str
    # Substrings that mark a URL as a product page. Kept loose on purpose:
    # brands restructure their sites, and over-filtering silently drops years.
    product_markers: tuple
    acquirer: str | None
    acquisition_year: int | None
    currency_hint: str = "USD"


BRANDS = {
    "byredo": Brand(
        slug="byredo",
        domain="byredo.com",
        product_markers=("/p/", "/product/", "/shop/", "eau-de-parfum", "/perfume/"),
        acquirer="Puig",
        acquisition_year=2022,
    ),
    # --- treatment group, fill in as you expand ---
    # lelabo.com holds 39 archived urls; the storefront is lelabofragrances.com.
    # Le Labo names products by collection (/classic-collection/santal-33), so
    # the usual /product//p/ markers match nothing here.
    "lelabo": Brand("lelabo", "lelabofragrances.com",
                    ("/classic-collection/", "/city-exclusive-collection/",
                     "/body-hair-face/", "/product", "/p/"),
                    "Estée Lauder", 2014),
    "fredericmalle": Brand("fredericmalle", "fredericmalle.com", ("/product", "/p/"), "Estée Lauder", 2015),
    "penhaligons": Brand("penhaligons", "penhaligons.com", ("/product", "/p/"), "Puig", 2015),
    "mfk": Brand("mfk", "franciskurkdjian.com", ("/product", "/p/"), "LVMH", 2017),
    "creed": Brand("creed", "creedboutique.com", ("/product", "/p/"), "Kering", 2023),
    # --- control group ---
    "xerjoff": Brand("xerjoff", "xerjoff.com", ("/product", "/p/"), None, None),
    "nishane": Brand("nishane", "nishane.com", ("/product", "/p/"), None, None),
    "marly": Brand("marly", "parfums-de-marly.com", ("/product", "/p/"), None, None),
    "roja": Brand("roja", "rojaparfums.com", ("/product", "/p/"), None, None),
    "bdk": Brand("bdk", "bdkparfums.com", ("/product", "/p/"), None, None),
    "zoologist": Brand("zoologist", "zoologistperfumes.com", ("/product", "/p/"), None, None),
}


# --------------------------------------------------------------------------
# Step 1 — CDX: what snapshots exist?
# --------------------------------------------------------------------------

def cdx_query(brand: Brand, year_from: int, year_to: int) -> list[dict]:
    """Ask the Wayback CDX API for every archived capture of this domain."""
    params = {
        "url": f"{brand.domain}/*",
        "output": "json",
        "fl": "timestamp,original,statuscode,digest",
        "filter": "statuscode:200",
        "from": f"{year_from}0101",
        "to": f"{year_to}1231",
        # collapse on digest: skip captures where the page content is byte-identical
        "collapse": "digest",
        "limit": "200000",
    }
    print(f"  querying CDX for {brand.domain} ({year_from}-{year_to})...")
    # More patient than the per-snapshot retries: this one call gates the whole
    # crawl, and CDX 503s have lasted several minutes in practice.
    for attempt in range(CDX_RETRIES):
        try:
            r = requests.get(CDX_API, params=params, headers=HEADERS, timeout=120)
            if r.status_code in (429, 502, 503, 504) or not r.text.strip():
                wait = min(DELAY * (attempt + 2) * 3, 300)
                print(f"    CDX unavailable ({r.status_code}), backing off {wait:.0f}s "
                      f"[{attempt + 1}/{CDX_RETRIES}]")
                time.sleep(wait)
                continue
            r.raise_for_status()
            break
        except requests.RequestException as e:
            print(f"    CDX retry {attempt+1}/{CDX_RETRIES}: {e}")
            time.sleep(min(DELAY * (attempt + 2) * 3, 300))
    else:
        raise RuntimeError(f"CDX query for {brand.domain} failed after {CDX_RETRIES} attempts")
    rows = r.json()
    if not rows:
        return []
    header, *body = rows
    snaps = [dict(zip(header, row)) for row in body]
    print(f"  {len(snaps):,} raw captures")
    return snaps


def filter_products(snaps: list[dict], brand: Brand) -> list[dict]:
    """Keep product pages only, then thin to one capture per URL per month.

    The monthly thinning is the important bit. Archive.org may hold 400
    captures of one page in a year; you need price *drift*, not noise.
    """
    kept = [
        s for s in snaps
        if any(m in s["original"].lower() for m in brand.product_markers)
        and not any(x in s["original"].lower() for x in
                    ("?", "/cart", "/account", "/search", ".jpg", ".png", ".css", ".js"))
    ]
    print(f"  {len(kept):,} look like product pages")

    seen, thinned = set(), []
    for s in sorted(kept, key=lambda x: x["timestamp"]):
        key = (s["original"].rstrip("/").lower(), s["timestamp"][:6])  # YYYYMM
        if key not in seen:
            seen.add(key)
            thinned.append(s)
    print(f"  {len(thinned):,} after monthly thinning")
    return thinned


# --------------------------------------------------------------------------
# Step 2 — fetch, with an on-disk cache
# --------------------------------------------------------------------------

def fetch_snapshot(timestamp: str, url: str, brand_slug: str) -> str | None:
    """Download one archived page. Cached, so re-runs cost nothing."""
    cache_dir = CACHE / brand_slug
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha1(f"{timestamp}{url}".encode()).hexdigest()[:20]
    path = cache_dir / f"{key}.html"

    if path.exists():
        return path.read_text(encoding="utf-8", errors="ignore")

    # 'id_' suffix asks the Wayback Machine for the original bytes,
    # without its injected toolbar and rewritten links.
    full = f"{WAYBACK}/{timestamp}id_/{url}"

    for attempt in range(RETRIES):
        try:
            r = requests.get(full, headers=HEADERS, timeout=TIMEOUT)
            time.sleep(DELAY)
            if r.status_code == 200:
                path.write_text(r.text, encoding="utf-8")
                return r.text
            if r.status_code in (429, 503):
                wait = DELAY * (attempt + 2) * 3
                print(f"    throttled, backing off {wait:.0f}s")
                time.sleep(wait)
                continue
            return None
        except requests.RequestException as e:
            print(f"    retry {attempt+1}/{RETRIES}: {e}")
            time.sleep(DELAY * (attempt + 2))
    return None


# --------------------------------------------------------------------------
# Step 3 — parse
# --------------------------------------------------------------------------

CURRENCY = {"$": "USD", "£": "GBP", "€": "EUR", "USD": "USD", "GBP": "GBP", "EUR": "EUR"}

# 4 digits, not 3: Creed sells 1000ml flacons, and \d{1,3} silently read
# "1000ML" as 0ml by matching the trailing "000".
SIZE_RE = re.compile(r"(\d{1,4}(?:\.\d)?)\s*(ml|mL|ML)\b")
PRICE_RE = re.compile(r"([$£€])\s?(\d{1,3}(?:[,\s]\d{3})*(?:\.\d{2})?)")


def _to_float(s: str) -> float | None:
    try:
        return float(s.replace(",", "").replace(" ", ""))
    except ValueError:
        return None


def parse_jsonld(soup: BeautifulSoup) -> list[dict]:
    """Structured data is the reliable path — use it whenever present."""
    out = []
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        for node in (data if isinstance(data, list) else [data]):
            if not isinstance(node, dict):
                continue
            if node.get("@type") not in ("Product", "IndividualProduct"):
                continue
            name = node.get("name", "")
            offers = node.get("offers", [])
            if isinstance(offers, dict):
                offers = [offers]
            for off in offers:
                if not isinstance(off, dict):
                    continue
                price = off.get("price") or off.get("lowPrice")
                if price is None:
                    continue
                out.append({
                    "product": name,
                    "price": _to_float(str(price)),
                    "currency": off.get("priceCurrency", ""),
                    # NOT sku: a numeric SKU here masquerades as a variant and
                    # suppresses the URL-size recovery in extract().
                    "variant": off.get("name") or "",
                    "source": "jsonld",
                })
    return out


def parse_shopify(html: str) -> list[dict]:
    """Many niche brands run Shopify, which embeds a product JSON blob."""
    out = []
    for m in re.finditer(r'var\s+meta\s*=\s*(\{.*?\});', html, re.S):
        try:
            meta = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        prod = meta.get("product", {})
        for v in prod.get("variants", []):
            amount = _to_float(str(v.get("price", "")))
            if amount is None:
                continue
            # Shopify keeps money in minor units, so a bare integer reads as cents.
            # Compare after coercion: the raw value may be an int or a string, and
            # comparing a string against 1000 raises.
            if amount > 1000:
                amount /= 100
            out.append({
                # str(): Shopify product ids are integers, and callers slice this
                # field, which crashed the first Shopify-backed brand we crawled.
                "product": str(prod.get("type") or prod.get("id") or ""),
                "price": amount,
                "currency": "",
                "variant": str(v.get("public_title") or v.get("name") or ""),
                "source": "shopify",
            })
    return out


def parse_visible(soup: BeautifulSoup) -> list[dict]:
    """Last resort: read prices off the rendered page.

    Noisier — picks up 'you may also like' blocks — so results carry
    source='visible' and should be spot-checked before use.
    """
    out = []
    title = soup.find("h1")
    name = title.get_text(strip=True) if title else ""

    candidates = soup.find_all(
        class_=re.compile(r"price|amount|cost", re.I)
    ) or soup.find_all(["span", "div", "p"])

    # Nested elements (a price <span> inside a price <div>) both match, so
    # collect into a dict keyed on (price, size) and keep the richest variant.
    found: dict[tuple, dict] = {}

    for el in candidates[:60]:
        text = el.get_text(" ", strip=True)
        if len(text) > 120:
            continue
        pm = PRICE_RE.search(text)
        if not pm:
            continue
        sm = SIZE_RE.search(text)
        price = _to_float(pm.group(2))
        variant = f"{sm.group(1)}ml" if sm else ""
        key = (price, variant or None)

        # A sized reading supersedes an unsized one at the same price.
        if variant:
            found.pop((price, None), None)
        elif any(k[0] == price and k[1] for k in found):
            continue

        found[key] = {
            "product": name,
            "price": price,
            "currency": CURRENCY.get(pm.group(1), ""),
            "variant": variant,
            "source": "visible",
        }

    out = list(found.values())
    return out


def extract(html: str, url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    # Every parser runs on every page, not a first-hit cascade. Cascading made
    # the parser a function of site era (pre-2021 visible, post-2021 jsonld),
    # which confounds parser choice with the acquisition being measured. Running
    # all of them yields the overlap needed to calibrate one against another.
    rows = parse_jsonld(soup) + parse_shopify(html) + parse_visible(soup)

    # Recover size from the URL slug whenever the variant doesn't carry one.
    url_size = SIZE_RE.search(url)
    for r in rows:
        if url_size and not SIZE_RE.search(r.get("variant") or ""):
            r["variant"] = f"{url_size.group(1)}ml"
        if not r.get("product"):
            r["product"] = url.rstrip("/").split("/")[-1].replace("-", " ")
    return rows


def size_ml(variant: str) -> float | None:
    m = SIZE_RE.search(variant or "")
    return float(m.group(1)) if m else None


# --------------------------------------------------------------------------
# Step 4 — orchestrate
# --------------------------------------------------------------------------

def run(brand: Brand, year_from: int, year_to: int, cdx_only: bool, limit: int | None):
    OUT.mkdir(exist_ok=True)

    snaps = cdx_query(brand, year_from, year_to)
    if not snaps:
        print("  no captures found — check the domain in BRANDS")
        return
    snaps = filter_products(snaps, brand)

    cdx_path = OUT / f"{brand.slug}_snapshots.csv"
    with cdx_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["timestamp", "original", "statuscode", "digest"])
        w.writeheader()
        w.writerows(snaps)
    print(f"  snapshot index -> {cdx_path}")

    if cdx_only:
        by_year: dict[str, int] = {}
        for s in snaps:
            by_year[s["timestamp"][:4]] = by_year.get(s["timestamp"][:4], 0) + 1
        print("\n  captures per year:")
        for y in sorted(by_year):
            print(f"    {y}  {'#' * min(by_year[y] // 5 + 1, 60)}  {by_year[y]}")
        return

    if limit:
        snaps = snaps[:limit]

    rows, failed = [], 0
    total = len(snaps)
    est = total * DELAY / 60
    print(f"\n  fetching {total:,} snapshots (~{est:.0f} min)...\n")

    for i, s in enumerate(snaps, 1):
        html = fetch_snapshot(s["timestamp"], s["original"], brand.slug)
        if not html:
            failed += 1
            continue
        for r in extract(html, s["original"]):
            if r["price"] is None or not (5 < r["price"] < 5000):
                continue  # drop parse artifacts
            ml = size_ml(r["variant"])
            rows.append({
                "brand": brand.slug,
                "acquirer": brand.acquirer or "",
                "acquisition_year": brand.acquisition_year or "",
                "date": f"{s['timestamp'][:4]}-{s['timestamp'][4:6]}-{s['timestamp'][6:8]}",
                "year": int(s["timestamp"][:4]),
                "years_from_acquisition": (
                    int(s["timestamp"][:4]) - brand.acquisition_year
                    if brand.acquisition_year else ""
                ),
                "product": r["product"][:120],
                "variant": r["variant"],
                "size_ml": ml or "",
                "price": r["price"],
                "currency": r["currency"] or brand.currency_hint,
                "price_per_ml": round(r["price"] / ml, 3) if ml else "",
                "parser": r["source"],
                "url": s["original"],
            })
        if i % 25 == 0:
            print(f"    {i:,}/{total:,}  ({len(rows):,} price rows, {failed} misses)")

    out_path = OUT / f"{brand.slug}_prices.csv"
    if rows:
        with out_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)

    print(f"\n  done: {len(rows):,} price rows, {failed} fetch failures")
    print(f"  -> {out_path}")
    if rows:
        by_parser: dict[str, int] = {}
        for r in rows:
            by_parser[r["parser"]] = by_parser.get(r["parser"], 0) + 1
        print(f"  parser mix: {by_parser}")
        print("  (spot-check any 'visible' rows before trusting them)")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("brand", nargs="?", help="brand slug, e.g. byredo")
    p.add_argument("--from", dest="year_from", type=int, default=2014)
    p.add_argument("--to", dest="year_to", type=int, default=2026)
    p.add_argument("--cdx-only", action="store_true",
                   help="show archive coverage without downloading pages")
    p.add_argument("--limit", type=int, help="stop after N snapshots (for testing)")
    p.add_argument("--list", action="store_true", help="list configured brands")
    a = p.parse_args()

    if a.list or not a.brand:
        print("configured brands:\n")
        for slug, b in BRANDS.items():
            tag = f"{b.acquirer} {b.acquisition_year}" if b.acquirer else "independent"
            print(f"  {slug:<16} {b.domain:<28} {tag}")
        return

    if a.brand not in BRANDS:
        sys.exit(f"unknown brand '{a.brand}' — run --list")

    brand = BRANDS[a.brand]
    print(f"\n{brand.slug.upper()}  ({brand.domain})")
    print(f"{'acquired by ' + brand.acquirer + ' in ' + str(brand.acquisition_year) if brand.acquirer else 'independent'}\n")
    run(brand, a.year_from, a.year_to, a.cdx_only, a.limit)


if __name__ == "__main__":
    main()
