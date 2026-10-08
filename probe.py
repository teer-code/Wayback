#!/usr/bin/env python3
"""
probe.py — decide whether a brand is worth crawling, before spending ~40 hours.

The Byredo pilot surfaced two failure modes that a full crawl can't detect until
it's over:

  1. JS-rendered eras. Byredo's 2019-2020 storefront loaded prices client-side,
     so the archived HTML holds no price at all. 77% of those product pages are
     unparseable — and that was the pre-acquisition baseline.
  2. Parser switches. Pre-2021 pages only yield to the regex parser, post-2021
     only to JSON-LD, and the two disagree by ~70% on price level. If a brand's
     parser switch lands near its acquisition, the two are confounded and the
     before/after result is uninterpretable.

This fetches a few product pages per year and reports which parsers fire, so
both failure modes show up in minutes instead of days.

Usage:
    python probe.py lelabo
    python probe.py --all --per-year 6
"""

import argparse
import random
import re
import sys
from collections import defaultdict

from bs4 import BeautifulSoup

from wayback_prices import (
    BRANDS, DELAY, cdx_query, fetch_snapshot,
    parse_jsonld, parse_shopify, parse_visible,
)

# Category/listing pages carry prices too, but they're the *tile* price of
# whatever happened to be featured — not a product's price. Byredo's v1 data
# drew ~22% of its pre-2021 rows from these.
LISTING = re.compile(
    r"/(perfume|fragrances?|shop|collections?|products)/?$"
    r"|explore|best-?sellers|new-?arrivals|/scents/?$|/category|/all/?$"
    # /collections/<anything> is Shopify's category route, not a product
    r"|/collections/.|/blogs?/",
    re.I,
)
# /products/ (Shopify) as well as /product/ — requiring the trailing slash on the
# singular form alone scored Creed on 355 urls when it has ~1,500.
PRODUCT = re.compile(r"eau-de-parfum|/p/|/products?/|parfum|cologne|edp|edt", re.I)
# Magento and friends put "/product/" inside their image paths
# (/media/catalog/product/cache/.../bois-15v100.jpg), so PRODUCT alone lets
# thumbnails through and they burn sample slots while yielding no price.
ASSET = re.compile(r"\.(jpg|jpeg|png|gif|webp|svg|css|js|ico|woff2?|ttf|pdf)(\?|$)"
                   r"|/media/|/static/|/cache/|/skin/|/assets/", re.I)


def product_pages(snaps: list[dict]) -> tuple[list[dict], str]:
    """Product pages if we can recognise them, otherwise every real page.

    PRODUCT encodes Byredo-ish URL conventions. Le Labo names products
    /classic-collection/santal-33, matching none of them, which made a strict
    filter report 'no product pages' for a brand that has thousands. When the
    strict filter keeps almost nothing, sample everything instead and say so —
    a diluted fire-rate is still evidence; a false zero is not.
    """
    real = [s for s in snaps
            if not ASSET.search(s["original"])
            and not LISTING.search(s["original"])
            and "?" not in s["original"]]
    strict = [s for s in real if PRODUCT.search(s["original"])]
    if len(strict) >= max(200, 0.02 * len(real)):
        return strict, "product-like urls"
    return real, ("ALL pages — product url patterns unrecognised, "
                  "so fire-rates are diluted by non-product pages")


def sample_by_year(snaps: list[dict], per_year: int) -> list[dict]:
    by_year = defaultdict(list)
    for s in snaps:
        by_year[s["timestamp"][:4]].append(s)
    rng = random.Random(0)
    out = []
    for year in sorted(by_year):
        pool = by_year[year]
        out += rng.sample(pool, min(per_year, len(pool)))
    return out


def probe(brand, year_from: int, year_to: int, per_year: int):
    print(f"\n{'=' * 74}")
    tag = (f"acquired by {brand.acquirer} in {brand.acquisition_year}"
           if brand.acquirer else "independent (control)")
    print(f"{brand.slug.upper()}  ({brand.domain})  —  {tag}")
    print("=" * 74)
    if brand.acquisition_year and brand.acquisition_year <= year_from + 1:
        print(f"  !! WINDOW TOO LATE: deal was {brand.acquisition_year} but the window "
              f"starts {year_from}, leaving <=1 pre-acquisition year.")
        print(f"     Any 'no pre-acquisition data' verdict below is an artefact "
              f"of the window. Re-run with --from {brand.acquisition_year - 4}.")

    try:
        snaps = cdx_query(brand, year_from, year_to)
    except Exception as e:
        print(f"  CDX FAILED: {e}")
        return
    if not snaps:
        print("  no captures — check the domain in BRANDS")
        return

    # Per-year capture counts come from the CDX index alone, so thin years show
    # up even where the url filter recognises nothing.
    captures = defaultdict(int)
    for s in snaps:
        captures[s["timestamp"][:4]] += 1
    print("  captures/year: " + "  ".join(f"{y}:{captures[y]:,}" for y in sorted(captures)))

    pages, how = product_pages(snaps)
    print(f"  {len(snaps):,} captures -> sampling from {len(pages):,} ({how})")
    if not pages:
        print("  VERDICT: nothing fetchable at all — check the domain.")
        return

    picked = sample_by_year(pages, per_year)
    mins = len(picked) * DELAY / 60
    print(f"  sampling {len(picked)} pages (~{mins:.0f} min at {DELAY:.0f}s/req)\n")

    stats = defaultdict(lambda: dict(n=0, jsonld=0, shopify=0, visible=0, both=0, none=0))
    for i, s in enumerate(picked, 1):
        html = fetch_snapshot(s["timestamp"], s["original"], brand.slug)
        year = s["timestamp"][:4]
        st = stats[year]
        st["n"] += 1
        if not html:
            st["none"] += 1
            continue
        soup = BeautifulSoup(html, "html.parser")
        j, sh, v = len(parse_jsonld(soup)), len(parse_shopify(html)), len(parse_visible(soup))
        st["jsonld"] += j > 0
        st["shopify"] += sh > 0
        st["visible"] += v > 0
        st["both"] += (j > 0 and v > 0)
        st["none"] += not (j or sh or v)
        if i % 20 == 0:
            print(f"    {i}/{len(picked)}")

    print(f"\n  {'year':<6}{'n':>4}{'jsonld':>9}{'shopify':>9}{'visible':>9}"
          f"{'both':>7}{'NONE':>7}   dominant")
    dominant = {}
    for year in sorted(stats):
        st = stats[year]
        n = st["n"] or 1
        pct = lambda k: f"{100 * st[k] / n:>7.0f}%"
        best = max(("jsonld", "shopify", "visible"), key=lambda k: st[k])
        dominant[year] = best if st[best] else "none"
        print(f"  {year:<6}{st['n']:>4}{pct('jsonld')}{pct('shopify')}{pct('visible')}"
              f"{100 * st['both'] / n:>6.0f}%{100 * st['none'] / n:>6.0f}%   {dominant[year]}")

    _verdict(brand, stats, dominant)


AVAIL = 0.33  # a parser "covers" a year if it fires on at least this share


def _coverage(stats):
    """Years each parser actually covers — not merely the year's top parser.

    Counting dominance hides the case that sank Byredo: one lone pre-acquisition
    year on the modern parser reads as 'spans both sides' while offering no
    pre-trend at all.
    """
    cov = {}
    for parser in ("jsonld", "shopify", "visible"):
        cov[parser] = {y for y, st in stats.items()
                       if st["n"] and st[parser] / st["n"] >= AVAIL}
    return cov


def _verdict(brand, stats, dominant):
    print(f"\n  {'-' * 70}")
    cov = _coverage(stats)
    n_min = min((st["n"] for st in stats.values() if st["n"]), default=0)
    if n_min < 8:
        print(f"  (low confidence: as few as {n_min} pages in some years — "
              f"re-run with a larger --per-year before deciding)")
    desert = sorted(y for y, st in stats.items()
                    if st["n"] and st["none"] / st["n"] >= 0.5)
    if desert:
        print(f"  DATA DESERT (>=50% of pages unparseable): {', '.join(desert)}")

    acq = brand.acquisition_year
    if not acq:
        best, years = max(cov.items(), key=lambda kv: len(kv[1]))
        print(f"  CONTROL BRAND — best single parser '{best}' covers "
              f"{len(years)}/{len(stats)} years")
        print("  VERDICT: usable as control" if len(years) >= 4
              else "  VERDICT: TOO SPARSE to serve as a control")
        return

    # Score each parser by how much of BOTH sides it spans on its own.
    scored = []
    for parser, years in cov.items():
        pre = sorted(y for y in years if int(y) < acq)
        post = sorted(y for y in years if int(y) > acq)
        # span is the binding side: a parser is only as useful as its thin half
        scored.append((min(len(pre), len(post)), len(pre) + len(post), parser, pre, post))
    scored.sort(reverse=True)
    for _, _, parser, pre, post in scored:
        if pre or post:
            print(f"  {parser:<8} pre-{acq}: {len(pre)} yr {pre}  "
                  f"post-{acq}: {len(post)} yr {post}")

    span, _, parser, pre, post = scored[0]
    thin = "pre" if len(pre) <= len(post) else "post"
    if span == 0:
        both_sides = (any(p for _, _, _, p, _ in scored if p)
                      and any(q for _, _, _, _, q in scored if q))
        if both_sides:
            print(f"  VERDICT: CONFOUNDED — no single parser spans {acq}.")
            print("           A pre/post jump would be a parser artifact, not a price.")
        else:
            print("  VERDICT: UNUSABLE — one side of the acquisition has no data.")
    elif span == 1:
        print(f"  VERDICT: WEAK — best parser '{parser}' has {len(pre)} pre / "
              f"{len(post)} post years; the {thin} side is a single year.")
        print("           Level shift measurable; trend is not. Controls essential.")
    else:
        print(f"  VERDICT: VIABLE — '{parser}' covers {len(pre)} pre and "
              f"{len(post)} post years. Crawl this one.")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("brand", nargs="?", help="brand slug, e.g. lelabo")
    p.add_argument("--all", action="store_true", help="probe every configured brand")
    p.add_argument("--from", dest="year_from", type=int, default=2014)
    p.add_argument("--to", dest="year_to", type=int, default=2026)
    p.add_argument("--per-year", type=int, default=10,
                   help="pages to sample per year (default 10; below ~8 the "
                        "per-year percentages get too noisy to act on)")
    a = p.parse_args()

    if a.all:
        targets = list(BRANDS.values())
    elif a.brand in BRANDS:
        targets = [BRANDS[a.brand]]
    else:
        sys.exit(f"unknown brand '{a.brand}' — run: python wayback_prices.py --list")

    for b in targets:
        probe(b, a.year_from, a.year_to, a.per_year)


if __name__ == "__main__":
    main()
