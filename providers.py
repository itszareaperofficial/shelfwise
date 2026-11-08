"""Data providers. Each yields (product_dict, offers_list) built ONLY from fields the provider returned.
Add a provider = write one generator and register it in PROVIDERS."""
import json, os, csv, re, io, time, threading, urllib.request, urllib.parse
from db import upsert_product, conn

CONTACT = os.environ.get("CONTACT_EMAIL", "set-CONTACT_EMAIL@example.com")
UA = f"ProductDiscovery/1.0 ({CONTACT})"

def get_json(url, headers=None, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))

def https(u): return u if isinstance(u, str) and re.match(r"^https?://", u.strip()) else None
def num(x):
    try: return float(str(x).replace(",", "").strip()) if x not in (None, "") else None
    except ValueError: return None
def first(*xs): return next((x for x in xs if x), None)

# ---- Open Food/Beauty/Products Facts (free, no key; data ODbL, images CC BY-SA) -------------------------------
OFF_SITES = {"openfoodfacts": ("world.openfoodfacts.org", "Food & Grocery"), "openbeautyfacts": ("world.openbeautyfacts.org", "Health & Beauty"),
             "openproductsfacts": ("world.openproductsfacts.org", None)}

def openfacts(query, limit=20):
    for name, (host, cat) in OFF_SITES.items():
        q = urllib.parse.urlencode({"search_terms": query, "search_simple": 1, "action": "process", "json": 1, "page_size": limit,
            "fields": "code,product_name,brands,categories,image_front_url,generic_name,quantity,ingredients_text,nutriscore_grade,nova_group,url"})
        try: data = get_json(f"https://{host}/cgi/search.pl?{q}")
        except Exception: continue
        for it in data.get("products", []):
            nm = (it.get("product_name") or "").strip()
            if not nm or not it.get("code"): continue
            specs = {k: v for k, v in {"Quantity": it.get("quantity"), "Ingredients": it.get("ingredients_text"),
                     "Nutri-Score": (it.get("nutriscore_grade") or "").upper() or None, "NOVA group": it.get("nova_group")}.items() if v}
            pros, cons = [], []
            if (it.get("nutriscore_grade") or "") in ("a", "b"): pros.append(f"Nutri-Score {it['nutriscore_grade'].upper()} (provider data)")
            if (it.get("nutriscore_grade") or "") in ("d", "e"): cons.append(f"Nutri-Score {it['nutriscore_grade'].upper()} (provider data)")
            if str(it.get("nova_group")) == "4": cons.append("NOVA group 4: ultra-processed (provider data)")
            page = https(it.get("url")) or f"https://{host}/product/{it['code']}"
            yield ({"source": name, "source_id": it["code"], "name": nm, "brand": (it.get("brands") or "").split(",")[0].strip() or None,
                    "gtin": it["code"], "category": cat, "category_path": it.get("categories"), "description": it.get("generic_name"),
                    "image_url": https(it.get("image_front_url")), "specs": specs, "pros": pros, "cons": cons,
                    "attribution": f"Data from {host.split('.',1)[1]} (ODbL). Images CC BY-SA.", "license": "ODbL / CC BY-SA"}, [])

# ---- Open Library (books; free, no key) ----------------------------------------------------------------------
def openlibrary(query, limit=20):
    q = urllib.parse.urlencode({"q": query, "limit": limit, "fields": "key,title,author_name,first_publish_year,cover_i,isbn,subject,ratings_average,ratings_count"})
    for it in get_json(f"https://openlibrary.org/search.json?{q}").get("docs", []):
        isbn = next((i for i in it.get("isbn", []) if len(i) == 13), None)
        author = ", ".join(it.get("author_name", [])[:3]) or None
        yield ({"source": "openlibrary", "source_id": it["key"], "name": it["title"], "brand": author, "gtin": isbn, "category": "Books & Education",
                "category_path": ", ".join(it.get("subject", [])[:8]), "image_url": f"https://covers.openlibrary.org/b/id/{it['cover_i']}-L.jpg" if it.get("cover_i") else None,
                "specs": {k: v for k, v in {"Author": author, "First published": it.get("first_publish_year"), "ISBN-13": isbn}.items() if v},
                "rating": it.get("ratings_average"), "rating_count": it.get("ratings_count") or 0,
                "attribution": "Data from Open Library (public domain / CC0 metadata).", "license": "CC0"},
               [{"seller": "Open Library", "url": f"https://openlibrary.org{it['key']}"}])

# ---- Best Buy Products API (free key: https://developer.bestbuy.com ; follow their terms of use) -------------
def bestbuy(query, limit=20):
    key = os.environ["BESTBUY_API_KEY"]
    words = "&".join(f"search={urllib.parse.quote(w)}" for w in re.findall(r"\w+", query)[:5])
    show = "sku,name,manufacturer,modelNumber,upc,salePrice,url,image,longDescription,customerReviewAverage,customerReviewCount,onlineAvailability,categoryPath.name,features.feature"
    data = get_json(f"https://api.bestbuy.com/v1/products({words})?apiKey={key}&format=json&pageSize={min(limit,100)}&show={show}")
    for it in data.get("products", []):
        if not https(it.get("url")): continue
        yield ({"source": "bestbuy", "source_id": str(it["sku"]), "name": it["name"], "brand": it.get("manufacturer"), "model": it.get("modelNumber"),
                "gtin": it.get("upc"), "category_path": " > ".join(c["name"] for c in it.get("categoryPath", [])), "description": it.get("longDescription"),
                "image_url": https(it.get("image")), "features": [f["feature"] for f in it.get("features", [])][:12], "price": it.get("salePrice"), "currency": "USD",
                "rating": it.get("customerReviewAverage"), "rating_count": it.get("customerReviewCount") or 0, "attribution": "Product data via Best Buy Products API."},
               [{"seller": "Best Buy", "url": it["url"], "price": it.get("salePrice"), "currency": "USD", "availability": "in_stock" if it.get("onlineAvailability") else "out_of_stock"}])

# ---- Generic feed importer: CSV or JSON list from any affiliate/merchant feed you are authorized to use ------
def feed(path, mapping=None, seller=None, source=None, demo=False):
    """Standard columns: id,name,brand,model,gtin,category,description,image_url,price,currency,url,availability,seller,official,rating,rating_count,spec_<Name>.
    `mapping` renames provider columns to these (e.g. {"title":"name","link":"url"})."""
    raw = urllib.request.urlopen(urllib.request.Request(path, headers={"User-Agent": UA}), timeout=60).read().decode("utf-8-sig") if https(path) else open(path, encoding="utf-8-sig").read()
    rows = json.loads(raw) if raw.lstrip().startswith(("[", "{")) else list(csv.DictReader(io.StringIO(raw)))
    source = source or "feed:" + re.sub(r"\W+", "_", os.path.basename(path))[:40]
    for r in rows:
        r = {(mapping or {}).get(k, k): v for k, v in r.items()}
        if not r.get("name") or not r.get("id"): continue
        specs = {k[5:]: v for k, v in r.items() if k.startswith("spec_") and v}
        price, url = num(r.get("price")), https(r.get("url"))
        yield ({"source": source, "source_id": str(r["id"]), "name": r["name"], "brand": r.get("brand"), "model": r.get("model"), "gtin": r.get("gtin") or None,
                "category_path": r.get("category"), "description": r.get("description"), "image_url": https(r.get("image_url")), "specs": specs,
                "price": price, "currency": r.get("currency"), "rating": num(r.get("rating")), "rating_count": int(num(r.get("rating_count")) or 0),
                "official_url": url if str(r.get("official")).lower() in ("1", "true", "yes") else None, "is_demo": demo,
                "attribution": r.get("attribution") or "Merchant feed."},
               [{"seller": r.get("seller") or seller or "Seller", "url": url, "price": price, "currency": r.get("currency"),
                 "availability": r.get("availability") or "unknown", "is_official": str(r.get("official")).lower() in ("1", "true", "yes")}] if url else [])

# ---- registry & discovery ------------------------------------------------------------------------------------
PROVIDERS = {"openfacts": (openfacts, lambda: True), "openlibrary": (openlibrary, lambda: True),
             "bestbuy": (bestbuy, lambda: bool(os.environ.get("BESTBUY_API_KEY")))}

def enabled(): return [n for n, (_, ok) in PROVIDERS.items() if ok()]

def ingest(provider, query, limit=20):
    n = 0
    for p, offers in PROVIDERS[provider][0](query, limit):
        upsert_product(p, offers); n += 1
    return n

_sem = threading.Semaphore(2)
def discover_async(query):
    """Background expansion of the catalog for a user query; each query is fetched at most once per 24h."""
    c = conn(); now = int(time.time()); key = query.lower().strip()
    if len(key) < 3 or not enabled() or os.environ.get("DISCOVERY", "1") == "0": return False
    r = c.execute("SELECT ts FROM discovered WHERE q=?", (key,)).fetchone()
    if r and now - r["ts"] < 86400: return False
    c.execute("INSERT OR REPLACE INTO discovered(q,ts) VALUES(?,?)", (key, now)); c.commit()
    def work():
        if not _sem.acquire(blocking=False): return
        try:
            for name in enabled():
                try: ingest(name, query, 20)
                except Exception as e: print(f"[discover] {name} failed: {e}")
        finally: _sem.release(); import db; db.close()
    threading.Thread(target=work, daemon=True).start()
    return True
