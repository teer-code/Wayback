"""Validate the three parsers against HTML shaped like real archived pages."""
from wayback_prices import extract, size_ml

# 1. Modern Byredo-style page with JSON-LD structured data
JSONLD = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product",
 "name":"Gypsy Water Eau de Parfum",
 "offers":[
   {"@type":"Offer","price":"235.00","priceCurrency":"USD","name":"50 ml"},
   {"@type":"Offer","price":"330.00","priceCurrency":"USD","name":"100 ml"}]}
</script></head><body><h1>Gypsy Water</h1></body></html>
"""

# 2. Shopify-backed niche brand
SHOPIFY = """
<html><body><script>
var meta = {"product":{"id":123,"type":"Eau de Parfum","variants":[
  {"id":1,"price":19500,"public_title":"50ml"},
  {"id":2,"price":27000,"public_title":"100ml"}]}};
</script></body></html>
"""

# 3. Older page, no structured data — visible-text fallback
VISIBLE = """
<html><body>
<h1>Gypsy Water</h1>
<div class="product-price"><span class="amount">$145.00</span> 50ml</div>
<div class="product-price"><span class="amount">$220.00</span> 100ml</div>
<div class="related"><p>Mojave Ghost $180.00</p></div>
</body></html>
"""

# 4. Size only in the URL slug
URLSIZE = """
<html><head><script type="application/ld+json">
{"@type":"Product","name":"Bal d'Afrique",
 "offers":{"@type":"Offer","price":"196.00","priceCurrency":"USD"}}
</script></head><body></body></html>
"""

cases = [
    ("JSON-LD (modern)", JSONLD, "https://byredo.com/us_en/p/gypsy-water-eau-de-parfum"),
    ("Shopify meta",     SHOPIFY, "https://example.com/products/gypsy-water"),
    ("Visible fallback", VISIBLE, "https://byredo.com/shop/gypsy-water"),
    ("Size from URL",    URLSIZE, "https://byredo.com/shop/bal-d-afrique-50ml"),
]

for label, html, url in cases:
    print(f"\n{label}")
    print("-" * 58)
    rows = extract(html, url)
    if not rows:
        print("  !! nothing extracted")
    for r in rows:
        ml = size_ml(r["variant"])
        ppm = f"{r['price']/ml:6.2f}/ml" if ml and r["price"] else "     -    "
        print(f"  {r['product'][:26]:<26} {str(r['variant']):>8}  "
              f"{r['price']:>8.2f} {r['currency']:<4} {ppm}  [{r['source']}]")
