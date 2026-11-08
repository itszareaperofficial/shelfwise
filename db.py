"""SQLite schema, taxonomy and upsert logic. Portable to PostgreSQL (see README: scaling)."""
import sqlite3, json, os, time, threading

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "catalog.db"))
_local = threading.local()

def conn():
    c = getattr(_local, "c", None)
    if c is None or getattr(_local, "path", None) != DB_PATH:
        os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
        c = sqlite3.connect(DB_PATH, timeout=30)
        c.row_factory = sqlite3.Row
        for p in ("journal_mode=WAL", "foreign_keys=ON", "synchronous=NORMAL"):
            c.execute("PRAGMA " + p)
        _local.c, _local.path = c, DB_PATH
    return c

def close():
    c = getattr(_local, "c", None)
    if c is not None: c.close(); _local.c = None   # also rolls back any half-finished transaction

SCHEMA = """
CREATE TABLE IF NOT EXISTS products(
  id INTEGER PRIMARY KEY, source TEXT NOT NULL, source_id TEXT NOT NULL,
  name TEXT NOT NULL, brand TEXT, model TEXT, gtin TEXT, category TEXT, category_path TEXT,
  description TEXT, image_url TEXT, specs TEXT DEFAULT '{}', features TEXT DEFAULT '[]',
  pros TEXT DEFAULT '[]', cons TEXT DEFAULT '[]', rating REAL, rating_count INTEGER DEFAULT 0,
  price_min REAL, price_max REAL, currency TEXT, official_url TEXT, attribution TEXT, license TEXT,
  is_demo INTEGER DEFAULT 0, views INTEGER DEFAULT 0, keywords TEXT, updated_at INTEGER,
  UNIQUE(source, source_id));
CREATE INDEX IF NOT EXISTS ix_p_cat ON products(category);
CREATE INDEX IF NOT EXISTS ix_p_gtin ON products(gtin);
CREATE INDEX IF NOT EXISTS ix_p_brand ON products(brand COLLATE NOCASE);
CREATE TABLE IF NOT EXISTS offers(
  id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
  origin TEXT NOT NULL, seller TEXT NOT NULL, url TEXT NOT NULL, price REAL, currency TEXT,
  availability TEXT DEFAULT 'unknown', is_official INTEGER DEFAULT 0, fetched_at INTEGER);
CREATE INDEX IF NOT EXISTS ix_o_p ON offers(product_id);
CREATE VIRTUAL TABLE IF NOT EXISTS products_fts USING fts5(name, brand, category, keywords,
  content='products', content_rowid='id', tokenize='unicode61 remove_diacritics 2');
CREATE TRIGGER IF NOT EXISTS p_ai AFTER INSERT ON products BEGIN
  INSERT INTO products_fts(rowid,name,brand,category,keywords) VALUES(new.id,new.name,new.brand,new.category,new.keywords); END;
CREATE TRIGGER IF NOT EXISTS p_ad AFTER DELETE ON products BEGIN
  INSERT INTO products_fts(products_fts,rowid,name,brand,category,keywords) VALUES('delete',old.id,old.name,old.brand,old.category,old.keywords); END;
CREATE TRIGGER IF NOT EXISTS p_au AFTER UPDATE ON products BEGIN
  INSERT INTO products_fts(products_fts,rowid,name,brand,category,keywords) VALUES('delete',old.id,old.name,old.brand,old.category,old.keywords);
  INSERT INTO products_fts(rowid,name,brand,category,keywords) VALUES(new.id,new.name,new.brand,new.category,new.keywords); END;
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT, salt BLOB, pw_hash BLOB, created INTEGER);
CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, user_id INTEGER REFERENCES users(id) ON DELETE CASCADE, expires INTEGER);
CREATE TABLE IF NOT EXISTS wishlists(id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id) ON DELETE CASCADE, name TEXT NOT NULL, created INTEGER);
CREATE TABLE IF NOT EXISTS wishlist_items(wishlist_id INTEGER REFERENCES wishlists(id) ON DELETE CASCADE,
  product_id INTEGER REFERENCES products(id) ON DELETE CASCADE, added INTEGER, PRIMARY KEY(wishlist_id, product_id));
CREATE TABLE IF NOT EXISTS history(user_id INTEGER REFERENCES users(id) ON DELETE CASCADE, kind TEXT, ref TEXT, label TEXT, ts INTEGER, PRIMARY KEY(user_id, kind, ref));
CREATE TABLE IF NOT EXISTS comparisons(id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id) ON DELETE CASCADE, name TEXT, product_ids TEXT, created INTEGER);
CREATE TABLE IF NOT EXISTS search_log(q TEXT, ts INTEGER, results INTEGER);
CREATE TABLE IF NOT EXISTS discovered(q TEXT PRIMARY KEY, ts INTEGER);
CREATE TABLE IF NOT EXISTS video_cache(product_id INTEGER PRIMARY KEY REFERENCES products(id) ON DELETE CASCADE, data TEXT, ts INTEGER);
"""

def init():
    conn().executescript(SCHEMA); conn().commit()

# name -> (icon, keywords used ONLY to file a product under a browse category)
TAXONOMY = {
 "Technology": ("💻", "laptop computer phone smartphone tablet monitor camera headphone earbud speaker router keyboard mouse printer television tv electronics audio drone watch smartwatch charger cable"),
 "Gaming": ("🎮", "game gaming console playstation xbox nintendo controller gamepad"),
 "Fashion": ("👟", "shoe sneaker boot clothing shirt jacket dress jeans pants apparel handbag jewelry fashion sock"),
 "Sports & Fitness": ("🏋️", "sport fitness gym yoga bicycle bike treadmill dumbbell football basketball tennis golf running"),
 "Home & Living": ("🛋️", "furniture sofa chair table bed mattress lamp rug kitchen cookware home decor bedding storage"),
 "Appliances": ("🧺", "appliance refrigerator washer dryer vacuum microwave oven dishwasher blender coffee maker fryer"),
 "Automotive": ("🚗", "car automotive tire motor vehicle motorcycle engine oil truck"),
 "Health & Beauty": ("🧴", "beauty cosmetic skincare shampoo soap lotion makeup perfume health vitamin supplement hygiene toothpaste"),
 "Food & Grocery": ("🥫", "food snack beverage drink cereal chocolate sauce grocery biscuit candy dairy"),
 "Books & Education": ("📚", "book novel textbook education course dictionary"),
 "Entertainment": ("🎬", "movie film music vinyl album dvd bluray instrument guitar piano"),
 "Outdoor Equipment": ("⛺", "outdoor camping tent hiking backpack sleeping fishing kayak grill"),
 "Toys & Kids": ("🧸", "toy lego doll puzzle kids baby stroller"),
 "Pets": ("🐾", "pet dog cat aquarium leash"),
 "Office & Stationery": ("🖇️", "office stationery pen notebook desk paper"),
 "Tools & DIY": ("🔧", "tool drill saw hammer diy hardware paint garden"),
}

def classify(text):
    t = " " + (text or "").lower() + " "
    best, score = "Other", 0
    for cat, (_, kws) in TAXONOMY.items():
        s = sum(2 if (" " + k) in t else 0 for k in kws.split())
        if s > score: best, score = cat, s
    return best

BLANKABLE = ["name","brand","model","gtin","category","category_path","description","image_url","attribution","license","official_url"]

def upsert_product(p, offers=()):
    """Insert/update a normalized product. Products sharing a GTIN from different sources are merged,
    so that one product page can list offers from several sellers. Nothing is invented: absent = NULL."""
    c, now = conn(), int(time.time())
    p = dict(p)
    p["category"] = p.get("category") or classify((p.get("category_path") or "") + " " + p["name"])
    row = c.execute("SELECT * FROM products WHERE source=? AND source_id=?", (p["source"], p["source_id"])).fetchone()
    merged = False
    if row is None and p.get("gtin"):
        row = c.execute("SELECT * FROM products WHERE gtin=? ORDER BY rating_count DESC LIMIT 1", (p["gtin"],)).fetchone()
        merged = row is not None
    if row is None:
        c.execute("INSERT INTO products(source,source_id,name,updated_at) VALUES(?,?,?,?)", (p["source"], p["source_id"], p["name"], now))
        row = c.execute("SELECT * FROM products WHERE source=? AND source_id=?", (p["source"], p["source_id"])).fetchone()
        merged = True  # row is blank: fill
    pid = row["id"]
    vals = {f: (row[f] or p.get(f)) if merged else (p.get(f) or row[f]) for f in BLANKABLE}
    specs = {**json.loads(row["specs"] or "{}"), **(p.get("specs") or {})}
    feats = p.get("features") or json.loads(row["features"] or "[]")
    pros = p.get("pros") or json.loads(row["pros"] or "[]"); cons = p.get("cons") or json.loads(row["cons"] or "[]")
    rating, rc = row["rating"], row["rating_count"] or 0
    if p.get("rating") is not None and (p.get("rating_count") or 0) >= rc: rating, rc = p["rating"], p.get("rating_count") or 0
    kw = " ".join(filter(None, [vals["category_path"], p.get("model") or row["model"], vals["gtin"], (vals["description"] or "")[:300]]))
    c.execute("""UPDATE products SET name=?,brand=?,model=?,gtin=?,category=?,category_path=?,description=?,image_url=?,attribution=?,license=?,
      official_url=?,specs=?,features=?,pros=?,cons=?,rating=?,rating_count=?,currency=COALESCE(?,currency),
      price_min=COALESCE(?,price_min),price_max=COALESCE(?,price_max),is_demo=?,keywords=?,updated_at=? WHERE id=?""",
      (*[vals[f] for f in BLANKABLE[:11]], json.dumps(specs), json.dumps(feats), json.dumps(pros), json.dumps(cons), rating, rc,
       p.get("currency"), p.get("price"), p.get("price"), int(bool(p.get("is_demo"))), kw, now, pid))
    if row["source"] == p["source"] and row["source_id"] == p["source_id"]:
        c.execute("DELETE FROM offers WHERE product_id=? AND origin=?", (pid, p["source"]))   # refresh own offers
    for o in offers:
        c.execute("DELETE FROM offers WHERE product_id=? AND origin=? AND seller=?", (pid, p["source"], o["seller"]))
        c.execute("INSERT INTO offers(product_id,origin,seller,url,price,currency,availability,is_official,fetched_at) VALUES(?,?,?,?,?,?,?,?,?)",
                  (pid, p["source"], o["seller"], o["url"], o.get("price"), o.get("currency"), o.get("availability") or "unknown", int(bool(o.get("is_official"))), now))
    r = c.execute("SELECT MIN(price),MAX(price),MAX(currency) FROM offers WHERE product_id=? AND price IS NOT NULL", (pid,)).fetchone()
    if r[0] is not None:
        c.execute("UPDATE products SET price_min=?,price_max=?,currency=? WHERE id=?", (r[0], r[1], r[2], pid))
    c.commit()
    return pid
