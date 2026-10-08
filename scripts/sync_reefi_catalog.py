#!/usr/bin/env python3
"""Sync Reefi products from sitemap into a high-performance local SQLite database with FTS5 search."""

import argparse
import concurrent.futures
import json
import logging
import os
import re
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("sync_reefi_catalog")

SITEMAP_URL = "https://reefi.me/sitemap_products.xml"
DEFAULT_DB_PATH = os.environ.get("REEFI_DB_PATH", "/app/data/products.db")
USER_AGENT = "Mozilla/5.0 (compatible; VoiceAI-CatalogSync/1.0; +https://reefi.me)"


def init_db(db_path: str) -> sqlite3.Connection:
    """Initialize SQLite database with products and FTS5 search tables."""
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE,
            name TEXT NOT NULL,
            category TEXT,
            description TEXT,
            price TEXT,
            old_price TEXT,
            discount TEXT,
            sku TEXT,
            in_stock INTEGER DEFAULT 1,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )

    cursor.execute(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS products_fts USING fts5(
            name,
            category,
            description,
            content='products',
            content_rowid='id',
            tokenize='unicode61'
        );
        """
    )

    cursor.execute(
        """
        CREATE TRIGGER IF NOT EXISTS products_ai AFTER INSERT ON products BEGIN
            INSERT INTO products_fts(rowid, name, category, description)
            VALUES (new.id, new.name, new.category, new.description);
        END;
        """
    )
    cursor.execute(
        """
        CREATE TRIGGER IF NOT EXISTS products_ad AFTER DELETE ON products BEGIN
            INSERT INTO products_fts(products_fts, rowid, name, category, description)
            VALUES('delete', old.id, old.name, old.category, old.description);
        END;
        """
    )
    cursor.execute(
        """
        CREATE TRIGGER IF NOT EXISTS products_au AFTER UPDATE ON products BEGIN
            INSERT INTO products_fts(products_fts, rowid, name, category, description)
            VALUES('delete', old.id, old.name, old.category, old.description);
            INSERT INTO products_fts(rowid, name, category, description)
            VALUES (new.id, new.name, new.category, new.description);
        END;
        """
    )

    conn.commit()
    return conn


def fetch_sitemap_urls(sitemap_url: str = SITEMAP_URL) -> List[str]:
    """Fetch product URLs from sitemap."""
    logger.info("Fetching sitemap from %s...", sitemap_url)
    req = urllib.request.Request(sitemap_url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        xml_data = resp.read()

    root = ET.fromstring(xml_data)
    urls = [
        loc.text.strip()
        for loc in root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
        if loc.text
    ]
    logger.info("Discovered %d product URLs from sitemap", len(urls))
    return urls


def parse_product_html(url: str, html: str) -> Optional[Dict[str, Any]]:
    """Parse product metadata, pricing, category, and features from HTML."""
    if not html:
        return None

    product_info = {}
    for m in re.finditer(
        r'<script\s+type=[\"\']application/ld\+json[\"\']>(.*?)</script>',
        html,
        re.DOTALL,
    ):
        try:
            data = json.loads(m.group(1))
            if data.get("@type") == "Product":
                product_info = data
                break
        except Exception:
            pass

    name = product_info.get("name")
    if not name:
        name_match = re.search(r'<h1[^>]*class=[\"\'][^\"\']*product-name[^\"\']*[\"\'][^>]*>(.*?)</h1>', html, re.DOTALL)
        if name_match:
            name = re.sub(r'<[^>]+>', '', name_match.group(1)).strip()

    if not name:
        return None

    desc = product_info.get("description")
    if not desc:
        meta_desc = re.search(r'<meta[^>]*name=[\"\']description[\"\'][^>]*content=[\"\'](.*?)[\"\']', html)
        if meta_desc:
            desc = meta_desc.group(1).strip()

    cat = product_info.get("category")
    sku = product_info.get("sku")

    price_match = re.search(r'<span class=\"price\">([\d.]+)\s*ر\.س\s*</span>', html)
    price = (price_match.group(1) + " ر.س") if price_match else None

    old_price_match = re.search(r'<del class=\"old\">([\d.]+)\s*ر\.س\s*</del>', html)
    old_price = (old_price_match.group(1) + " ر.س") if old_price_match else None

    discount_match = re.search(r'وفر\s*(\d+%?)', html)
    discount = (discount_match.group(1) + "%") if discount_match and not discount_match.group(1).endswith("%") else (discount_match.group(1) if discount_match else None)

    in_stock = 1 if "out-of-stock" not in html.lower() else 0

    return {
        "url": url,
        "name": name.strip(),
        "category": cat.strip() if cat else "",
        "description": desc.strip() if desc else "",
        "price": price or "غير محدد",
        "old_price": old_price or "",
        "discount": discount or "",
        "sku": sku or "",
        "in_stock": in_stock,
    }


def quote_url(url: str) -> str:
    """Safely URL-encode non-ASCII characters in URL paths."""
    try:
        parsed = urllib.parse.urlsplit(url)
        encoded_path = urllib.parse.quote(parsed.path, safe="/%")
        encoded_query = urllib.parse.quote(parsed.query, safe="=&%")
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, encoded_path, encoded_query, parsed.fragment))
    except Exception:
        return url


def fetch_and_parse(url: str, retries: int = 2) -> Optional[Dict[str, Any]]:
    """Fetch a single product URL with retries."""
    safe_url = quote_url(url)
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(safe_url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=12) as resp:
                html = resp.read().decode("utf-8", errors="ignore")
            return parse_product_html(url, html)
        except Exception as e:
            if attempt == retries:
                logger.warning("Failed to fetch %s: %s", url, e)
                return None
            time.sleep(0.5 * (attempt + 1))
    return None


def sync_catalog(db_path: str, max_workers: int = 15, limit: Optional[int] = None) -> int:
    """Crawl sitemap and populate SQLite products database."""
    urls = fetch_sitemap_urls()
    if limit:
        urls = urls[:limit]

    conn = init_db(db_path)
    cursor = conn.cursor()

    logger.info("Starting concurrent download with %d workers for %d products...", max_workers, len(urls))
    start_time = time.time()
    success_count = 0

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_url = {executor.submit(fetch_and_parse, url): url for url in urls}
        for future in concurrent.futures.as_completed(future_to_url):
            data = future.result()
            if data:
                cursor.execute(
                    """
                    INSERT INTO products (url, name, category, description, price, old_price, discount, sku, in_stock, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(url) DO UPDATE SET
                        name=excluded.name,
                        category=excluded.category,
                        description=excluded.description,
                        price=excluded.price,
                        old_price=excluded.old_price,
                        discount=excluded.discount,
                        sku=excluded.sku,
                        in_stock=excluded.in_stock,
                        updated_at=CURRENT_TIMESTAMP;
                    """,
                    (
                        data["url"],
                        data["name"],
                        data["category"],
                        data["description"],
                        data["price"],
                        data["old_price"],
                        data["discount"],
                        data["sku"],
                        data["in_stock"],
                    ),
                )
                success_count += 1
                if success_count % 50 == 0:
                    conn.commit()
                    logger.info("Progress: saved %d / %d products...", success_count, len(urls))

    conn.commit()
    elapsed = time.time() - start_time
    logger.info("Catalog sync complete! Saved %d products to %s in %.2fs", success_count, db_path, elapsed)
    conn.close()
    return success_count


def search_catalog(db_path: str, query: str, limit: int = 5) -> List[Dict[str, Any]]:
    """Ultra-fast search for products by name, category, or description."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    clean_q = re.sub(r'[^\w\s]', ' ', query).strip()
    words = [w for w in clean_q.split() if len(w) > 1]
    
    results = []
    if words:
        fts_query = " OR ".join([f'"{w}"*' for w in words])
        try:
            cursor.execute(
                """
                SELECT p.id, p.name, p.price, p.old_price, p.discount, p.category, p.description, p.url
                FROM products_fts f
                JOIN products p ON f.rowid = p.id
                WHERE products_fts MATCH ?
                ORDER BY rank
                LIMIT ?;
                """,
                (fts_query, limit),
            )
            results = [dict(row) for row in cursor.fetchall()]
        except Exception:
            results = []

    if not results:
        like_terms = [f"%{w}%" for w in words]
        if like_terms:
            where_clauses = " OR ".join(["name LIKE ? OR category LIKE ? OR description LIKE ?" for _ in like_terms])
            params = []
            for t in like_terms:
                params.extend([t, t, t])
            params.append(limit)
            cursor.execute(
                f"""
                SELECT id, name, price, old_price, discount, category, description, url
                FROM products
                WHERE {where_clauses}
                LIMIT ?;
                """,
                params,
            )
            results = [dict(row) for row in cursor.fetchall()]

    conn.close()
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Reefi Store Catalog Sync")
    parser.add_argument("--db", default=DEFAULT_DB_PATH, help="Path to SQLite database")
    parser.add_argument("--workers", type=int, default=15, help="Concurrent workers")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of products")
    parser.add_argument("--search", type=str, default=None, help="Test search query")
    args = parser.parse_args()

    if args.search:
        hits = search_catalog(args.db, args.search)
        print(f"Search results for '{args.search}' ({len(hits)} hits):")
        for h in hits:
            print(f"- {h['name']} | السعر: {h['price']} (قبل: {h['old_price']}) | الخصم: {h['discount']}")
            print(f"  الفئة: {h['category'][:60]}...")
            print(f"  الوصف: {h['description'][:100]}...")
            print(f"  الرابط: {h['url']}\n")
    else:
        sync_catalog(args.db, max_workers=args.workers, limit=args.limit)
