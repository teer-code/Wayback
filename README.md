# Does a conglomerate acquisition make a niche fragrance more expensive?

I pulled **159,292 historical prices** out of the Internet Archive to find out.

The answer: **niche fragrance prices rose 13–21% between 2022 and 2024 — and the
conglomerate-owned brand rose the least.**

---

## The question

The received wisdom in fragrance circles is a sequence: a conglomerate buys a
niche house, the house gets commercialised, and prices get hiked. Byredo went to
Puig in 2022. Creed went to Kering in 2023. Le Labo and Frédéric Malle went to
Estée Lauder years before that.

It's a testable claim, and nobody seems to have tested it, because the data is
awkward: brands don't publish price history, and nobody archives it on purpose.

But the Internet Archive has been quietly photographing these websites for a
decade. So the prices exist — you just have to go and get them.

## What I found

### Everyone raised prices. The independent brands raised them more.

Same product, same size, year on year, indexed to 2022 = 100:

| year | Creed *(Kering, 2023)* | Zoologist *(independent)* | Parfums de Marly *(independent)* |
|------|------:|------:|------:|
| 2020 |  97.6 |  94.3 |     — |
| 2021 |  97.6 |  94.3 | 100.0 |
| 2022 | 100.0 | 100.0 | 100.0 |
| **2023** | **110.6** | **117.0** | **112.2** |
| 2024 | 110.6 | 120.0 | 124.4 |
| 2025 | 108.2 | 114.3 | 126.8 |
| 2026 | 108.2 | 114.3 | **139.0** |

Kering closed on Creed in late 2023. Creed stepped up 10.6% that year — which
looks like a textbook acquisition effect until you notice that **both brands
nobody acquired stepped up in the same year, by more.** By 2026 the independents
are far ahead of the conglomerate-owned brand.

### The receipts

Actual archived US list prices:

**Creed Aventus**
| size | 2020 | 2022 | 2023 | now |
|------|-----:|-----:|-----:|----:|
| 50 ml | $325 | $335 | $365 | $380 |
| 100 ml | $435 | $445 | $495 | $510 |
| 1000 ml | $1,600 | $1,695 | $1,850 | $1,900 |

**Byredo Gypsy Water**
| size | 2021 | 2022 | 2023 | 2024 | now |
|------|-----:|-----:|-----:|-----:|----:|
| 50 ml | $190 | $196 | $202 | $225 | $235 |
| 100 ml | $270 | $276 | $280 | $320 | $330 |

**Zoologist** (full bottle): $145 in 2019 → $175 in 2022 → $200 now.

### The headline number

Comparing the *same bottle in the same size* before the deal (2021–22) against
after it (2024–25):

| brand | products matched | price change |
|-------|----------------:|-------------:|
| **Creed** — acquired by Kering 2023 | 129 | **+13.3%** |
| Zoologist — independent | 26 | +21.2% |
| Parfums de Marly — independent | 62 | +14.1% |

Creed's increase sits *inside* the range set by brands that were never bought.
**There is no conglomerate premium visible in this data.**

## What this does and doesn't prove

It is worth being exact, because the easy version of this story is wrong.

**Supported:**
- Niche fragrance repriced sharply across 2022–24, roughly 13–21% on
  like-for-like products.
- Creed's post-acquisition increase was indistinguishable from independent peers.
- The apparent 2023 "acquisition step" in Creed is a market-wide move — it shows
  up in the control brands too.

**Not supported:**
- *"Conglomerates don't raise prices."* One acquisition was testable to this
  standard. That's a sample of one.
- *"Kering suppressed prices."* The estimate ranges from −4.4 to +3.6 percentage
  points depending on specification. That rules out a **large** effect. It cannot
  resolve a small one, or even its direction.
- Anything about Byredo/Puig. Its data only supports one clean pre-deal year —
  not enough to run the comparison.

These are **list prices from brands' own websites**. Discounting, retailer
pricing and the grey market are invisible here.

## Method

The plain version: *compare the acquired brand against brands nobody acquired,
over the same years, using the same products.*

The longer version:

1. **Find the snapshots.** The Internet Archive's CDX API lists every capture it
   holds for a domain. Filter to product pages, then keep one capture per URL per
   month — you want price drift, not 400 copies of the same page.
2. **Fetch them.** With the `id_` modifier, which returns the original archived
   bytes rather than Archive's replay wrapper. 5s between requests; everything
   cached to disk so re-runs are free.
3. **Parse three ways.** JSON-LD (schema.org structured data), Shopify's embedded
   product JSON, and as a last resort regex over rendered text. Every row is
   tagged with which parser produced it — that tag turned out to matter enormously.
4. **Match like with like.** Compare the same product *and* the same size across
   periods. Without this, a brand that merely launched expensive new bottles looks
   like it raised prices.
5. **Difference the differences.** Subtract the control brands' change from the
   treated brand's change. Whatever moved the whole market cancels out; what
   survives is specific to the acquisition.

The assumption this rests on is that Creed would have moved like the controls
absent the deal. You can't prove that, but you can check whether they moved
together *beforehand* — and they did (flat and parallel, 2020–22, in the table
above).

## The part I didn't expect: most of the brands were unusable

Eleven brands were planned. **Five had no recoverable pre-acquisition data at
all**, and finding that out was most of the work.

| brand | problem |
|-------|---------|
| Maison Francis Kurkdjian | JavaScript-rendered storefront 2013–2020. Eight consecutive years where **100% of archived product pages contain no price** — the prices were loaded client-side and never captured. |
| Le Labo | 104 total captures across its four pre-acquisition years. The Archive barely crawled the site before Estée Lauder bought it. |
| Xerjoff, Nishane, BDK | Same JS-rendering problem, different years. Nishane: 0 usable years out of 5. |
| Roja Parfums | Crawled fine (50,254 rows) but the product catalogue turned over 74% between periods, and five distinct products showed byte-identical $245 → $120 transitions — a parsing artifact, not repricing. Excluded. |

**And the brand I picked as the pilot was the worst possible choice.** Byredo's
site moved from server-rendered HTML to JSON-LD around 2021 — which means the
*measurement instrument changed in the same window as the Puig acquisition*. The
two parsers disagree by ~70% on price level ($120 vs $205 median), and there are
**zero** pages where both fire, so the offset can't be calibrated. Any
before/after result for Byredo would have been measuring the parser, not Puig.

Creed worked precisely because its 2023 deal sits *inside* a single parser era,
with Shopify's structured data spanning both sides — plus 3,045 pages where two
independent parsers both fired and **agreed on the price 100% of the time**.

That's the real lesson. The hard part wasn't the statistics. It was establishing
that the numbers meant the same thing in 2021 as in 2025.

## Tooling

A full crawl is ~5–20 hours per brand. Discovering a brand is unusable *after*
that is expensive, so [`probe.py`](probe.py) screens one in about 10 minutes: it
samples ~10 archived product pages per year and reports which parsers fire, which
years are empty, and whether any single parser spans the acquisition.

```bash
python probe.py creed --from 2018 --per-year 10
```

```
  year     n   jsonld  shopify  visible   both   NONE   dominant
  2020    20      0%      80%      80%     0%    20%   shopify
  2022    20     30%      70%       0%     0%    30%   shopify
  2023    20     65%      80%      70%    60%    20%   shopify
  2024    20     85%      85%      85%    85%    15%   jsonld
  ------------------------------------------------------------
  VERDICT: VIABLE — 'shopify' covers 3 pre and 3 post years
```

It caught a dead domain (Le Labo's configured site had 39 archived URLs; the real
storefront had 8,000+) and four unusable brands before any crawl started.

## Reproduce it

```bash
pip install requests beautifulsoup4 pandas

python probe.py --all --per-year 10          # which brands are even viable
python wayback_prices.py creed --cdx-only    # check archive coverage, 1 API call
python wayback_prices.py creed --limit 25    # smoke test the parser
python wayback_prices.py creed               # full crawl (hours)
```

Be patient with the Internet Archive — 5s between requests, and it will throttle
you anyway. It's a free public service doing you a favour.

## Data

| file | rows | role |
|------|-----:|------|
| `data/byredo_prices.csv` | 65,046 | treatment (Puig 2022) — parser confound, not testable |
| `data/roja_prices.csv` | 50,254 | control — excluded, catalogue instability |
| `data/creed_prices.csv` | 20,067 | **treatment (Kering 2023)** |
| `data/zoologist_prices.csv` | 15,562 | **control** |
| `data/marly_prices.csv` | 8,363 | **control** |

One row per product × size × snapshot month. `parser` column is your confidence
signal: `jsonld` and `shopify` are structured data; `visible` is regex-scraped
and should be spot-checked.

## Open threads

- Bootstrap confidence intervals on the difference estimate (currently point
  estimates only).
- Monthly rather than annual granularity — Kering closed in ~October 2023, so
  annual buckets blur the event.
- Byredo via a different route: its 2021–25 JSON-LD series is internally
  consistent even if the before/after comparison isn't available.
