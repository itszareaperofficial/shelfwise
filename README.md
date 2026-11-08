# Shelfwise: free product discovery (no direct sales)

Search products, see who sells them, compare, and click through to official stores and retailers.
Backend: Python 3.10+ standard library only (SQLite + FTS5). Frontend: vanilla JS. **No installs, no build step.**

## Run
Easiest: install Python from python.org, then double-click `start.bat` (Windows) or `start.command` (Mac; Linux: `sh start.command`). Your browser opens the site.

Or from a terminal:
```bash
python ingest.py --demo        # optional: 6 clearly labelled DEMO rows to preview the UI offline
python server.py               # http://localhost:8000   (PORT, HOST, DB_PATH env vars)
python tests/test_api.py       # 25 end-to-end API tests (offline)
```

## Fill the catalog from real sources
```bash
export CONTACT_EMAIL=you@example.com            # Open Facts asks API users to identify themselves
python ingest.py --provider openfacts --query "headphones"
python ingest.py --provider openlibrary --query "dune"
export BESTBUY_API_KEY=...                      # free key at developer.bestbuy.com; enables the Best Buy provider
python ingest.py --crawl                        # seed terms across all enabled providers; run from cron
python ingest.py --feed walmart.csv --seller Walmart --map '{"title":"name","link":"url","sku":"id"}'
```
**Continuous discovery:** when a search returns fewer than 8 results, the server queries every enabled provider in the
background (once per query per 24 h) and the results page refreshes itself. Set `DISCOVERY=0` to turn this off.

| Provider | Needs | Gives |
|---|---|---|
| Open Food / Beauty / Products Facts | nothing | names, brands, images, ingredients, GTIN (no prices) |
| Open Library | nothing | books, covers, ratings, ISBN (no prices) |
| Best Buy Products API | free key | price, availability, ratings, features, product URL |
| Feed importer (CSV/JSON) | a feed you are authorised to use | anything: Walmart, Awin, CJ, Impact, Google Merchant exports |

Amazon (Product Advertising API), Walmart and eBay need affiliate/developer approval and have their own terms
(including limits on caching prices). Add each as a generator in `providers.py` yielding `(product, offers)` and register it in `PROVIDERS`.

**Videos:** each product page has a Videos section. Set `YOUTUBE_API_KEY` (free, from Google Cloud Console, YouTube Data API v3) to show real YouTube results,
cached for 7 days to save quota. Without a key it shows labelled YouTube and TikTok search links only. Social-media listings are not scraped; they would need an official feed.

## Data integrity rules (enforced in code)
* A field is stored only if a provider returned it. Otherwise it is NULL and the UI says "not available".
* **Direct listings** (`offers`) come only from provider data. **Search links** (Amazon, Walmart, Best Buy, Google Shopping, "find the official site")
  are generated from the GTIN or name and are labelled as searches, never as confirmed listings.
* Products with the same GTIN from different sources merge into one page with several sellers.
* Pros and cons appear only when derived from provider facts (for example Nutri-Score). Review text is never invented.
* Images are hot-linked from the provider, not copied. Each product page shows its attribution and licence.

## Security
PBKDF2-SHA256 (310k iterations, per-user salt), constant-time comparison, random bearer tokens stored hashed (30-day expiry, no cookies so no CSRF),
auth rate limiting, parameterised SQL, strict CSP, output escaping, http(s)-only outbound links with `rel="noopener nofollow sponsored"`.
Run it behind HTTPS (Caddy or nginx) in production; set `HOST=0.0.0.0` only behind that proxy.

## Scaling to millions of products
SQLite + FTS5 handles a few million rows on one machine. Beyond that keep the API and swap the parts: Postgres (the tables port directly),
OpenSearch/Meilisearch/Typesense for search and facets, Redis for rate limits and the discovery cache, a job queue running `ingest.py` per provider,
a CDN for static files, and a WSGI/ASGI server instead of `http.server`.

## Files
`server.py` API and static host · `db.py` schema, taxonomy, merge logic · `providers.py` data sources · `ingest.py` CLI · `static/` web app · `tests/` fixture and tests
