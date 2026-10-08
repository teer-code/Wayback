# Fragrance price history — Byredo pilot

Extracts historical retail prices from Internet Archive snapshots, to test
whether conglomerate acquisition measurably changes a niche house's pricing.

Byredo is the pilot: acquired by **Puig in 2022**, recent enough that Wayback
coverage is dense on both sides of the deal.

## Setup

```bash
pip install requests beautifulsoup4
```

## Run

Start here — this costs one API call and tells you whether the project is viable:

```bash
python wayback_prices.py byredo --cdx-only --from 2014 --to 2026
```

You get a histogram of archived captures per year. **What you're looking for:**
meaningful coverage in 2019–2021 (pre-Puig) *and* 2023–2026 (post-Puig). If the
pre-2022 years are thin, the whole before/after design is in trouble and you
want to know that now, not after a month of scraping.

Then a small real fetch to confirm parsing works on actual pages:

```bash
python wayback_prices.py byredo --limit 20
```

Inspect `data/byredo_prices.csv`. Check the `parser` column — `jsonld` and
`shopify` rows are trustworthy, `visible` rows need spot-checking.

Then the full run:

```bash
python wayback_prices.py byredo --from 2014 --to 2026
```

At 5s/request this takes hours. Run it under `nohup` or `screen`. Everything
is cached to `cache/`, so an interrupted run resumes for free.

## Validation anchor

The scraper's most recent rows should land near these. Verified September 2026,
US retail:

| Product | Size | Price | Price/ml |
|---|---|---|---|
| Gypsy Water EDP | 50 ml | $235 | $4.70 |
| Gypsy Water EDP | 100 ml | $330 | $3.30 |

If your 2026 output doesn't match, the parser is picking up the wrong element —
fix that before running the other eleven brands.

## Output schema

`data/<brand>_prices.csv`, one row per product × size × snapshot month:

| Column | Notes |
|---|---|
| `brand`, `acquirer`, `acquisition_year` | From the BRANDS config |
| `date`, `year` | Snapshot date, not release date |
| `years_from_acquisition` | Negative = before the deal. This is your x-axis. |
| `product`, `variant`, `size_ml` | |
| `price`, `currency`, `price_per_ml` | **`price_per_ml` is the comparable unit** |
| `parser` | `jsonld` \| `shopify` \| `visible` — your confidence signal |
| `url` | For manual verification |

## Design notes

**Monthly thinning.** Archive.org may hold hundreds of captures of one page per
year. The script keeps one per URL per month. You want price drift, not noise.

**`id_` URLs.** Snapshots are fetched with the `id_` suffix, which returns the
original archived bytes without the Wayback toolbar and link rewriting. Without
it you parse Archive's chrome instead of the page.

**Loose product matching.** `product_markers` is deliberately permissive. Brands
restructure their sites — Byredo's URLs have changed shape more than once —
and over-filtering silently drops entire years without telling you.

**Rate limiting is not optional.** 5s delay, exponential backoff on 429/503.
Archive.org will block you, and it's a free public service doing you a favour.

## Expanding

All eleven other brands are pre-configured in `BRANDS`. Verify each domain is
right before running — several have changed since acquisition:

```bash
python wayback_prices.py --list
```

Control brands (Xerjoff, Nishane, Parfums de Marly, Roja, BDK, Zoologist) are
what separate "Puig raised prices" from "everyone raised prices." Don't skip them.

## Known limitations

- Prices are **list prices from the brand's own site**, not transaction prices.
  Discounting and grey market are invisible here.
- Currency isn't inflation-adjusted or FX-normalised in the CSV. Do that in
  analysis, not collection — keep raw data raw.
- Regional sites (`/us_en/`, `/uk_en/`) may both appear. Filter by locale in
  analysis or restrict `product_markers` to one region.
