#!/usr/bin/env python3
"""Catalog builder. Examples:
  python ingest.py --provider openfacts --query "chocolate" --limit 30
  python ingest.py --crawl                      # seed terms across all enabled providers (rate-limit friendly; run from cron)
  python ingest.py --feed feed.csv --seller Walmart --map '{"title":"name","link":"url","sku":"id"}'
  python ingest.py --demo                       # load clearly-labelled DEMO rows to preview the UI offline"""
import argparse, json, time, os
import db, providers
SEEDS = ["laptop","smartphone","headphones","television","camera","gaming console","sneakers","backpack","sofa","coffee maker","vacuum",
         "shampoo","moisturizer","chocolate","novel","textbook","bicycle","tent","lego","dog food","drill","guitar","monitor","keyboard","running shoes"]
if __name__ == "__main__":
    a = argparse.ArgumentParser()
    a.add_argument("--provider"); a.add_argument("--query"); a.add_argument("--limit", type=int, default=20)
    a.add_argument("--crawl", action="store_true"); a.add_argument("--feed"); a.add_argument("--seller"); a.add_argument("--map")
    a.add_argument("--source"); a.add_argument("--demo", action="store_true")
    a = a.parse_args(); db.init()
    if a.demo: a.feed, a.source = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tests", "demo_feed.csv"), "demo"
    if a.feed:
        n = 0
        for p, o in providers.feed(a.feed, json.loads(a.map) if a.map else None, a.seller, a.source, demo=a.demo): db.upsert_product(p, o); n += 1
        print(f"feed: {n} products")
    elif a.crawl:
        for q in SEEDS:
            for name in providers.enabled():
                try: print(q, name, providers.ingest(name, q, a.limit))
                except Exception as e: print(q, name, "failed:", e)
                time.sleep(6)  # Open Facts search is limited to ~10 requests/min
    elif a.provider and a.query: print(providers.ingest(a.provider, a.query, a.limit), "products")
    else: print("enabled providers:", providers.enabled())
