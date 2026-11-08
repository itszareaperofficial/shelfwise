#!/usr/bin/env python3
"""Zero-dependency backend + static host. Run: python server.py  (PORT env, default 8000)."""
import html, json, os, re, time, hashlib, hmac, secrets, mimetypes, urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
import db, providers
from db import conn, TAXONOMY

ROOT = os.path.dirname(os.path.abspath(__file__)); STATIC = os.path.join(ROOT, "static")
ITER = 310_000; PER = 24; MIN_RESULTS = 8
CARD = """p.id,p.name,p.brand,p.category,p.image_url,p.rating,p.rating_count,p.price_min,p.price_max,p.currency,p.is_demo,
  (SELECT COUNT(*) FROM offers o WHERE o.product_id=p.id) AS offer_count"""
_hits = {}

def rate_ok(ip, limit=10, window=60):
    now = time.time(); h = [t for t in _hits.get(ip, []) if now - t < window]
    _hits[ip] = h + [now]; return len(h) < limit

def hash_pw(pw, salt): return hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, ITER)
def rows(sql, a=()): return [dict(r) for r in conn().execute(sql, a).fetchall()]
def one(sql, a=()): r = conn().execute(sql, a).fetchone(); return dict(r) if r else None

def retailer_links(p):
    term = p.get("gtin") or " ".join(filter(None, [p.get("brand") if p["source"] != "openlibrary" else None, p["name"]]))[:120]
    q = urllib.parse.quote_plus(term)
    L = [("Amazon", f"https://www.amazon.com/s?k={q}"), ("Walmart", f"https://www.walmart.com/search?q={q}"),
         ("Best Buy", f"https://www.bestbuy.com/site/searchpage.jsp?st={q}"), ("Google Shopping", f"https://www.google.com/search?tbm=shop&q={q}")]
    off = urllib.parse.quote_plus(f"{p.get('brand') or ''} {p['name']} official site".strip())
    L.insert(0, ("Find the official site", f"https://www.google.com/search?q={off}"))
    return [{"seller": s, "url": u, "kind": "search"} for s, u in L]

def fts_query(q): return " ".join(f'"{t}"*' for t in re.findall(r"\w+", q.lower())[:8])

def run_search(a, uid=None):
    q = (a.get("q") or "").strip()[:100]; fq = fts_query(q)
    frm = "products p" + (" JOIN products_fts ON products_fts.rowid=p.id" if fq else ""); base, args = [], []
    if fq: base.append("products_fts MATCH ?"); args.append(fq)
    if a.get("min"): base.append("p.price_min>=?"); args.append(float(a["min"]))
    if a.get("max"): base.append("p.price_min<=?"); args.append(float(a["max"]))
    if a.get("rating"): base.append("p.rating>=?"); args.append(float(a["rating"]))
    if a.get("available"): base.append("EXISTS(SELECT 1 FROM offers o WHERE o.product_id=p.id AND o.availability='in_stock')")
    extra, eargs = [], []
    if a.get("category"): extra.append("p.category=?"); eargs.append(a["category"])
    if a.get("brand"): extra.append("p.brand=? COLLATE NOCASE"); eargs.append(a["brand"])
    W = lambda parts: (" WHERE " + " AND ".join(parts)) if parts else ""
    order = {"price_asc": "p.price_min IS NULL, p.price_min ASC", "price_desc": "p.price_min IS NULL, p.price_min DESC",
             "rating": "p.rating IS NULL, p.rating DESC, p.rating_count DESC", "popularity": "p.rating_count DESC, p.views DESC"
             }.get(a.get("sort"), "bm25(products_fts,10,5,2,1)" if fq else "p.rating_count DESC, p.views DESC")
    total = conn().execute(f"SELECT COUNT(*) FROM {frm}{W(base+extra)}", args + eargs).fetchone()[0]
    page = max(1, int(a.get("page") or 1))
    items = rows(f"SELECT {CARD} FROM {frm}{W(base+extra)} ORDER BY {order} LIMIT ? OFFSET ?", args + eargs + [PER, (page - 1) * PER])
    cats = rows(f"SELECT p.category AS name, COUNT(*) AS n FROM {frm}{W(base)} GROUP BY p.category ORDER BY n DESC", args)
    bparts = base + (extra[:1] if a.get("category") else []) + ["p.brand IS NOT NULL"]
    brands = rows(f"SELECT p.brand AS name, COUNT(*) AS n FROM {frm}{W(bparts)} GROUP BY p.brand ORDER BY n DESC LIMIT 12", args + (eargs[:1] if a.get("category") else []))
    discovering = False
    if q and page == 1:
        conn().execute("INSERT INTO search_log VALUES(?,?,?)", (q.lower(), int(time.time()), total)); conn().commit()
        if uid: touch_history(uid, "search", q.lower(), q)
        if total < MIN_RESULTS: discovering = providers.discover_async(q)
    return {"q": q, "total": total, "page": page, "pages": (total + PER - 1) // PER, "items": items, "categories": cats, "brands": brands, "discovering": discovering}

def touch_history(uid, kind, ref, label):
    c = conn(); c.execute("INSERT OR REPLACE INTO history VALUES(?,?,?,?,?)", (uid, kind, str(ref), label, int(time.time())))
    c.execute("DELETE FROM history WHERE user_id=? AND kind=? AND ref NOT IN (SELECT ref FROM history WHERE user_id=? AND kind=? ORDER BY ts DESC LIMIT 30)", (uid, kind, uid, kind)); c.commit()

def product_detail(pid, uid):
    p = one("SELECT * FROM products WHERE id=?", (pid,))
    if not p: return None
    conn().execute("UPDATE products SET views=views+1 WHERE id=?", (pid,)); conn().commit()
    for k in ("specs", "features", "pros", "cons"): p[k] = json.loads(p[k] or ("{}" if k == "specs" else "[]"))
    p["offers"] = rows("SELECT seller,url,price,currency,availability,is_official FROM offers WHERE product_id=? ORDER BY is_official DESC, price IS NULL, price", (pid,))
    p["search_links"] = retailer_links(p)
    p["similar"] = rows(f"SELECT {CARD} FROM products p WHERE p.category=? AND p.id!=? ORDER BY (p.brand=?) DESC, p.rating_count DESC LIMIT 8", (p["category"], pid, p["brand"]))
    for k in ("keywords", "source_id"): p.pop(k, None)
    if uid: touch_history(uid, "product", pid, p["name"])
    return p

def product_videos(pid):
    """Real YouTube videos when YOUTUBE_API_KEY is set (cached 7 days); otherwise labelled search links only."""
    p = one("SELECT name,brand FROM products WHERE id=?", (pid,))
    if not p: return None
    term = " ".join(filter(None, [p["brand"], p["name"], "review"]))[:120]; q = urllib.parse.quote_plus(term)
    out = {"mode": "links", "videos": [], "links": [{"site": "YouTube", "url": f"https://www.youtube.com/results?search_query={q}"},
                                                     {"site": "TikTok", "url": f"https://www.tiktok.com/search?q={q}"}]}
    key = os.environ.get("YOUTUBE_API_KEY")
    if not key: return out
    c = one("SELECT data,ts FROM video_cache WHERE product_id=?", (pid,))
    if c and time.time() - c["ts"] < 7 * 86400: out.update(mode="youtube", videos=json.loads(c["data"])); return out
    try:
        d = providers.get_json("https://www.googleapis.com/youtube/v3/search?" + urllib.parse.urlencode({"part": "snippet", "type": "video", "maxResults": 4, "q": term, "key": key}))
        vids = [{"id": i["id"]["videoId"], "title": html.unescape(i["snippet"]["title"]), "channel": html.unescape(i["snippet"]["channelTitle"]), "thumb": i["snippet"]["thumbnails"]["medium"]["url"]}
                for i in d.get("items", []) if i.get("id", {}).get("videoId")]
        conn().execute("INSERT OR REPLACE INTO video_cache VALUES(?,?,?)", (pid, json.dumps(vids), int(time.time()))); conn().commit()
        out.update(mode="youtube", videos=vids)
    except Exception as e: print("youtube failed:", repr(e))
    return out

def home(uid):
    cnt = {r["name"]: r["n"] for r in rows("SELECT category AS name, COUNT(*) AS n FROM products GROUP BY category")}
    cats = [{"name": k, "icon": v[0], "count": cnt.get(k, 0)} for k, v in TAXONOMY.items()]
    trending = rows("SELECT q, COUNT(*) AS n FROM search_log WHERE ts>? AND results>0 GROUP BY q ORDER BY n DESC LIMIT 10", (int(time.time()) - 14 * 86400,))
    sel = lambda w, o: rows(f"SELECT {CARD} FROM products p {w} ORDER BY {o} LIMIT 8")
    out = {"total": sum(cnt.values()), "categories": cats, "trending": [t["q"] for t in trending],
           "popular": sel("", "p.views DESC, p.rating_count DESC"), "featured": sel("WHERE p.image_url IS NOT NULL AND p.rating IS NOT NULL", "p.rating DESC, p.rating_count DESC"),
           "recent": sel("", "p.updated_at DESC"), "providers": providers.enabled(), "recommended": []}
    if uid:
        mine = [r["category"] for r in rows("SELECT DISTINCT p.category FROM history h JOIN products p ON p.id=CAST(h.ref AS INTEGER) WHERE h.user_id=? AND h.kind='product' ORDER BY h.ts DESC LIMIT 3", (uid,))]
        if mine: out["recommended"] = rows(f"SELECT {CARD} FROM products p WHERE p.category IN ({','.join('?'*len(mine))}) ORDER BY p.rating_count DESC, p.views DESC LIMIT 8", mine)
    return out

class H(BaseHTTPRequestHandler):
    server_version = "Discover/1.0"
    def log_message(self, *a): pass
    def send(self, code, body, ctype="application/json", extra=None):
        b = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code); self.send_header("Content-Type", ctype); self.send_header("Content-Length", str(len(b)))
        for k, v in {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY",
                     "Content-Security-Policy": "default-src 'self'; img-src https: data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
                     **(extra or {})}.items(): self.send_header(k, v)
        self.end_headers(); self.wfile.write(b)
    def err(self, code, msg): self.send(code, {"error": msg})
    def user(self):
        h = self.headers.get("Authorization", "")
        if not h.startswith("Bearer "): return None
        r = one("SELECT u.id,u.email,u.name FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>?", (hashlib.sha256(h[7:].encode()).hexdigest(), int(time.time())))
        return r
    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n > 100_000: raise ValueError("too large")
        try: d = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError: raise ValueError("invalid JSON")
        if not isinstance(d, dict): raise ValueError("invalid JSON")
        return d

    def do_GET(self): self.route("GET")
    def do_POST(self): self.route("POST")
    def do_PATCH(self): self.route("PATCH")
    def do_DELETE(self): self.route("DELETE")

    def route(self, m):
        u = urllib.parse.urlparse(self.path); path = u.path; q = {k: v[0] for k, v in urllib.parse.parse_qs(u.query).items()}
        try:
            if path.startswith("/api/"): return self.api(m, path[5:].strip("/"), q)
            if m != "GET": return self.err(405, "method not allowed")
            f = os.path.normpath(os.path.join(STATIC, path[len("/static/"):] if path.startswith("/static/") else "index.html"))
            if not f.startswith(STATIC) or not os.path.isfile(f): f = os.path.join(STATIC, "index.html")
            ct = mimetypes.guess_type(f)[0] or "application/octet-stream"
            self.send(200, open(f, "rb").read(), ct + ("; charset=utf-8" if ct.startswith("text") or "javascript" in ct else ""), {"Cache-Control": "no-cache"})
        except ValueError as e: self.err(400, str(e))
        except Exception as e: print("error:", repr(e)); self.err(500, "server error")
        finally: db.close()

    def api(self, m, p, q):
        me = self.user(); uid = me["id"] if me else None; c = conn()
        def need():
            if not uid: raise PermissionError()
        try:
            if m == "GET":
                if p == "health": return self.send(200, {"ok": True, "providers": providers.enabled(), "products": c.execute("SELECT COUNT(*) FROM products").fetchone()[0]})
                if p == "home": return self.send(200, home(uid))
                if p == "search": return self.send(200, run_search(q, uid))
                if p == "suggest":
                    fq = fts_query(q.get("q", ""))
                    return self.send(200, [r["name"] for r in rows("SELECT p.name FROM products p JOIN products_fts ON products_fts.rowid=p.id WHERE products_fts MATCH ? ORDER BY p.rating_count DESC LIMIT 6", (fq,))] if fq else [])
                if mm := re.fullmatch(r"product/(\d+)", p):
                    d = product_detail(int(mm[1]), uid); return self.send(200, d) if d else self.err(404, "product not found")
                if mm := re.fullmatch(r"video/(\d+)", p):
                    d = product_videos(int(mm[1])); return self.send(200, d) if d else self.err(404, "product not found")
                if p == "compare":
                    ids = [int(i) for i in q.get("ids", "").split(",") if i.isdigit()][:4]
                    out = [d for d in (product_detail(i, None) for i in ids) if d]
                    for d in out: d.pop("similar", None)
                    return self.send(200, out)
                if p == "me": return self.send(200, me) if me else self.err(401, "not signed in")
                need()
                if p == "wishlists":
                    wl = rows("SELECT id,name FROM wishlists WHERE user_id=? ORDER BY id", (uid,))
                    for w in wl: w["items"] = rows(f"SELECT {CARD} FROM wishlist_items wi JOIN products p ON p.id=wi.product_id WHERE wi.wishlist_id=? ORDER BY wi.added DESC", (w["id"],))
                    return self.send(200, wl)
                if p == "history": return self.send(200, rows("SELECT kind,ref,label FROM history WHERE user_id=? ORDER BY ts DESC LIMIT 40", (uid,)))
                if p == "comparisons": return self.send(200, [{**r, "product_ids": json.loads(r["product_ids"])} for r in rows("SELECT id,name,product_ids FROM comparisons WHERE user_id=? ORDER BY id DESC", (uid,))])
            else:
                d = self.body() if self.headers.get("Content-Length") else {}
                if p in ("auth/register", "auth/login"):
                    if not rate_ok(self.client_address[0]): return self.err(429, "Too many attempts. Wait a minute and try again.")
                    email = str(d.get("email", "")).strip().lower(); pw = str(d.get("password", ""))
                    if not re.fullmatch(r"[^@\s]{1,64}@[^@\s]{1,255}\.[^@\s]{2,}", email): return self.err(400, "Enter a valid email address.")
                    if p == "auth/register":
                        if not (8 <= len(pw) <= 200): return self.err(400, "Password must be at least 8 characters.")
                        salt = secrets.token_bytes(16)
                        try: cur = c.execute("INSERT INTO users(email,name,salt,pw_hash,created) VALUES(?,?,?,?,?)", (email, str(d.get("name", ""))[:60] or email.split("@")[0], salt, hash_pw(pw, salt), int(time.time())))
                        except Exception: return self.err(409, "An account with this email already exists.")
                        c.execute("INSERT INTO wishlists(user_id,name,created) VALUES(?,?,?)", (cur.lastrowid, "Favorites", int(time.time()))); c.commit(); u_id = cur.lastrowid
                    else:
                        r = c.execute("SELECT id,salt,pw_hash FROM users WHERE email=?", (email,)).fetchone()
                        ok = hmac.compare_digest(hash_pw(pw, r["salt"] if r else b"x" * 16), r["pw_hash"] if r else b"")
                        if not (r and ok): return self.err(401, "Email or password is incorrect.")
                        u_id = r["id"]
                    tok = secrets.token_urlsafe(32)
                    c.execute("INSERT INTO sessions VALUES(?,?,?)", (hashlib.sha256(tok.encode()).hexdigest(), u_id, int(time.time()) + 30 * 86400)); c.commit()
                    return self.send(200, {"token": tok, "user": one("SELECT id,email,name FROM users WHERE id=?", (u_id,))})
                need()
                if p == "auth/logout":
                    c.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(self.headers["Authorization"][7:].encode()).hexdigest(),)); c.commit(); return self.send(200, {"ok": True})
                if p == "me" and m == "PATCH":
                    if d.get("name") is not None: c.execute("UPDATE users SET name=? WHERE id=?", (str(d["name"])[:60], uid))
                    if d.get("new_password"):
                        r = c.execute("SELECT salt,pw_hash FROM users WHERE id=?", (uid,)).fetchone()
                        if not hmac.compare_digest(hash_pw(str(d.get("current_password", "")), r["salt"]), r["pw_hash"]): return self.err(403, "Current password is incorrect.")
                        if len(str(d["new_password"])) < 8: return self.err(400, "Password must be at least 8 characters.")
                        salt = secrets.token_bytes(16); c.execute("UPDATE users SET salt=?,pw_hash=? WHERE id=?", (salt, hash_pw(d["new_password"], salt), uid))
                    c.commit(); return self.send(200, one("SELECT id,email,name FROM users WHERE id=?", (uid,)))
                if p == "me" and m == "DELETE":
                    r = c.execute("SELECT salt,pw_hash FROM users WHERE id=?", (uid,)).fetchone()
                    if not hmac.compare_digest(hash_pw(str(d.get("password", "")), r["salt"]), r["pw_hash"]): return self.err(403, "Password is incorrect.")
                    c.execute("DELETE FROM users WHERE id=?", (uid,)); c.commit(); return self.send(200, {"ok": True})
                if p == "wishlists" and m == "POST":
                    name = str(d.get("name", "")).strip()[:60]
                    if not name: return self.err(400, "Give the wishlist a name.")
                    cur = c.execute("INSERT INTO wishlists(user_id,name,created) VALUES(?,?,?)", (uid, name, int(time.time()))); c.commit(); return self.send(200, {"id": cur.lastrowid, "name": name, "items": []})
                if mm := re.fullmatch(r"wishlists/(\d+)", p):
                    if not one("SELECT 1 FROM wishlists WHERE id=? AND user_id=?", (mm[1], uid)): return self.err(404, "wishlist not found")
                    if m == "DELETE": c.execute("DELETE FROM wishlists WHERE id=?", (mm[1],)); c.commit(); return self.send(200, {"ok": True})
                if mm := re.fullmatch(r"wishlists/(\d+)/items(?:/(\d+))?", p):
                    if not one("SELECT 1 FROM wishlists WHERE id=? AND user_id=?", (mm[1], uid)): return self.err(404, "wishlist not found")
                    if m == "POST":
                        if not one("SELECT 1 FROM products WHERE id=?", (d.get("product_id"),)): return self.err(404, "product not found")
                        c.execute("INSERT OR IGNORE INTO wishlist_items VALUES(?,?,?)", (mm[1], d["product_id"], int(time.time())))
                    elif m == "DELETE" and mm[2]: c.execute("DELETE FROM wishlist_items WHERE wishlist_id=? AND product_id=?", (mm[1], mm[2]))
                    c.commit(); return self.send(200, {"ok": True})
                if p == "comparisons" and m == "POST":
                    ids = [int(i) for i in d.get("product_ids", [])][:4]
                    if len(ids) < 2: return self.err(400, "Pick at least two products.")
                    cur = c.execute("INSERT INTO comparisons(user_id,name,product_ids,created) VALUES(?,?,?,?)", (uid, str(d.get("name") or "My comparison")[:60], json.dumps(ids), int(time.time()))); c.commit(); return self.send(200, {"id": cur.lastrowid})
                if mm := re.fullmatch(r"comparisons/(\d+)", p) and m == "DELETE":
                    c.execute("DELETE FROM comparisons WHERE id=? AND user_id=?", (re.fullmatch(r"comparisons/(\d+)", p)[1], uid)); c.commit(); return self.send(200, {"ok": True})
                if p == "history" and m == "DELETE": c.execute("DELETE FROM history WHERE user_id=?", (uid,)); c.commit(); return self.send(200, {"ok": True})
            return self.err(404, "not found")
        except PermissionError: return self.err(401, "Sign in to use this feature.")
        except (TypeError, KeyError): return self.err(400, "invalid request")

if __name__ == "__main__":
    db.init(); port = int(os.environ.get("PORT", 8000))
    print(f"http://localhost:{port}  providers: {providers.enabled()}")
    ThreadingHTTPServer((os.environ.get("HOST", "127.0.0.1"), port), H).serve_forever()
