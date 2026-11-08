"""End-to-end API test against a throwaway DB (offline). Run: python tests/test_api.py"""
import os, sys, json, tempfile, threading, urllib.request, urllib.error
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(), "t.db"); os.environ["DISCOVERY"] = "0"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db, providers, server
from http.server import ThreadingHTTPServer
db.init()
for p, o in providers.feed(os.path.join(os.path.dirname(__file__), "demo_feed.csv"), source="demo", demo=True): db.upsert_product(p, o)
srv = ThreadingHTTPServer(("127.0.0.1", 0), server.H); threading.Thread(target=srv.serve_forever, daemon=True).start()
B = f"http://127.0.0.1:{srv.server_port}"
def call(m, path, body=None, tok=None):
    r = urllib.request.Request(B + path, method=m, data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", **({"Authorization": "Bearer " + tok} if tok else {})})
    try:
        with urllib.request.urlopen(r) as x: return x.status, json.loads(x.read())
    except urllib.error.HTTPError as e: return e.code, json.loads(e.read())
ok = lambda c, msg: print(("PASS " if c else "FAIL ") + msg) or bool(c)
res = []
s, d = call("GET", "/api/search?q=aurora"); res.append(ok(s == 200 and d["total"] == 2, f"search 'aurora' -> {d['total']} (GTIN merge: 2 phones)"))
s, d = call("GET", "/api/search?q=aur"); res.append(ok(d["total"] == 2, "prefix search"))
s, d = call("GET", "/api/search?q=0000000000017"); res.append(ok(d["total"] == 1, "search by GTIN"))
s, d = call("GET", "/api/search?q=aurora&sort=price_desc&min=500"); res.append(ok(d["total"] == 1 and d["items"][0]["name"].endswith("X2"), "price filter + sort"))
s, d = call("GET", "/api/search?available=1"); res.append(ok(d["total"] == 3, f"availability filter -> {d['total']}"))
s, d = call("GET", "/api/search?category=Technology"); res.append(ok(d["total"] >= 3, f"category browse -> {d['total']} {[c['name'] for c in d['categories']]}"))
pid = call("GET", "/api/search?q=X1")[1]["items"][0]["id"]
s, d = call("GET", f"/api/product/{pid}"); res.append(ok(len(d["offers"]) == 2 and d["offers"][0]["is_official"] == 1 and d["search_links"], "product: 2 offers, official first, retailer search links"))
res.append(ok(d["rating"] == 4.4 and d["description"].startswith("Synthetic"), "only provider-supplied data"))
s, v = call("GET", f"/api/video/{pid}"); res.append(ok(v["mode"] == "links" and len(v["links"]) == 2 and call("GET", "/api/video/999999")[0] == 404, "videos: search links without API key"))
s, d = call("GET", "/api/product/999999"); res.append(ok(s == 404, "404 on unknown product"))
s, d = call("GET", "/api/compare?ids=1,2,3"); res.append(ok(s == 200 and len(d) == 3, "compare"))
s, d = call("GET", "/api/home"); res.append(ok(d["total"] >= 5 and len(d["categories"]) > 10, "home"))
res.append(ok(call("GET", "/api/wishlists")[0] == 401, "wishlists require login"))
s, d = call("POST", "/api/auth/register", {"email": "a@b.co", "password": "short"}); res.append(ok(s == 400, "weak password rejected"))
s, d = call("POST", "/api/auth/register", {"email": "a@b.co", "password": "correct horse"}); tok = d.get("token"); res.append(ok(s == 200 and tok, "register"))
res.append(ok(call("POST", "/api/auth/register", {"email": "a@b.co", "password": "correct horse"})[0] == 409, "duplicate email"))
res.append(ok(call("POST", "/api/auth/login", {"email": "a@b.co", "password": "wrong password"})[0] == 401, "bad login"))
tok = call("POST", "/api/auth/login", {"email": "a@b.co", "password": "correct horse"})[1]["token"]
call("GET", f"/api/product/{pid}", tok=tok)
s, wl = call("GET", "/api/wishlists", tok=tok); res.append(ok(wl[0]["name"] == "Favorites", "default Favorites list"))
call("POST", f"/api/wishlists/{wl[0]['id']}/items", {"product_id": pid}, tok)
s, n = call("POST", "/api/wishlists", {"name": "Gifts"}, tok); call("POST", f"/api/wishlists/{n['id']}/items", {"product_id": pid}, tok)
s, wl = call("GET", "/api/wishlists", tok=tok); res.append(ok(len(wl) == 2 and len(wl[0]["items"]) == 1, "save to multiple wishlists"))
call("DELETE", f"/api/wishlists/{wl[0]['id']}/items/{pid}", tok=tok); res.append(ok(len(call("GET", "/api/wishlists", tok=tok)[1][0]["items"]) == 0, "remove item"))
s, h = call("GET", "/api/history", tok=tok); res.append(ok(any(x["kind"] == "product" for x in h), "recently viewed saved"))
s, c = call("POST", "/api/comparisons", {"name": "phones", "product_ids": [1, 2]}, tok); res.append(ok(s == 200 and len(call("GET", "/api/comparisons", tok=tok)[1]) == 1, "saved comparison"))
res.append(ok(call("PATCH", "/api/me", {"current_password": "nope", "new_password": "newpassword1"}, tok)[0] == 403, "password change needs current password"))
res.append(ok(call("POST", "/api/auth/logout", {}, tok)[0] == 200 and call("GET", "/api/me", tok=tok)[0] == 401, "logout invalidates token"))
r = urllib.request.urlopen(B + "/"); res.append(ok(b"<div id=\"app\"" in r.read() and "Content-Security-Policy" in r.headers, "SPA + CSP header"))
res.append(ok(b"ThreadingHTTPServer" not in urllib.request.urlopen(B + "/static/../server.py").read(), "path traversal blocked"))
print(f"\n{sum(res)}/{len(res)} passed"); sys.exit(0 if all(res) else 1)
