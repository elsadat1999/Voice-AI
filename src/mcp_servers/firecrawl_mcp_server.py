#!/usr/bin/env python3
"""Firecrawl MCP server for Voice AI (scraping, crawling, and web search)."""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional, Tuple

FIRECRAWL_API_URL = os.environ.get(
    "FIRECRAWL_API_URL", "http://firecrawl-service.voice-ai.svc.cluster.local:3002"
).rstrip("/")
FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "").strip()

# Optional list of comma-separated domains allowed (defaults to reefi.me)
def _normalize_domain(raw_val: str) -> str:
    raw_val = raw_val.strip().lower()
    if "://" in raw_val:
        from urllib.parse import urlparse
        return (urlparse(raw_val).netloc or "").split(":")[0]
    return raw_val.split("/")[0].split(":")[0]


raw_allowed = os.environ.get("ALLOWED_DOMAINS", "reefi.me").strip()
ALLOWED_DOMAINS = [
    _normalize_domain(d) for d in raw_allowed.split(",") if d.strip()
]
if not ALLOWED_DOMAINS:
    ALLOWED_DOMAINS = ["reefi.me"]


def is_domain_allowed(url_or_domain: str) -> bool:
    """Check if the given URL belongs to the allowed domains list."""
    if not ALLOWED_DOMAINS:
        return True
    from urllib.parse import urlparse

    raw = url_or_domain if "://" in url_or_domain else f"https://{url_or_domain}"
    parsed = urlparse(raw)
    host = (parsed.netloc or "").lower().split(":")[0]
    return any(host == allowed or host.endswith("." + allowed) for allowed in ALLOWED_DOMAINS)


import re
import threading
import time

# In-memory cache for ultra-low latency: (timestamp, (content, spoken))
_CACHE: Dict[str, Tuple[float, Tuple[str, str]]] = {}
CACHE_TTL_SECONDS = 600  # 10 minutes TTL


def get_from_cache(key: str) -> Optional[Tuple[str, str]]:
    """Retrieve result from in-memory cache if not expired."""
    item = _CACHE.get(key)
    if not item:
        return None
    cached_time, val = item
    if (time.time() - cached_time) < CACHE_TTL_SECONDS:
        return val
    _CACHE.pop(key, None)
    return None


def put_in_cache(key: str, val: Tuple[str, str]) -> None:
    """Store result in in-memory cache."""
    _CACHE[key] = (time.time(), val)


def clean_markdown_for_voice(text: str) -> str:
    """Strip images, raw media links, and markdown clutter to drastically reduce tokens and speed up LLM generation."""
    if not text:
        return ""
    # 1. Strip markdown images: ![alt](url)
    text = re.sub(r'!\[.*?\]\(.*?\)', '', text)
    # 2. Strip empty link brackets or image remnants: [](url)
    text = re.sub(r'\[\s*\]\([^\)]+\)', '', text)
    # 3. Simplify markdown links [Text](url) to just Text
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    # 4. Strip raw URLs inside parens
    text = re.sub(r'\(https?://[^\s)]+\)', '', text)
    # 5. Remove empty brackets
    text = re.sub(r'\[\s*\]|\(\s*\)', '', text)
    # 6. Remove headers symbols (###)
    text = re.sub(r'#{1,6}\s*', '', text)
    # 7. Normalize whitespace
    return " ".join(text.split())


def send_response(req_id: Any, result: Any) -> None:
    """Send JSON-RPC 2.0 response via newline-delimited JSON."""
    msg = {"jsonrpc": "2.0", "id": req_id, "result": result}
    body = json.dumps(msg, ensure_ascii=False)
    sys.stdout.buffer.write((body + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


def _make_request(endpoint: str, payload: Dict[str, Any], timeout: int = 10) -> Dict[str, Any]:
    url = f"{FIRECRAWL_API_URL}{endpoint}"
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if FIRECRAWL_API_KEY:
        headers["Authorization"] = f"Bearer {FIRECRAWL_API_KEY}"

    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


import sqlite3

def _get_db_path() -> Optional[str]:
    candidates = [
        os.environ.get("REEFI_DB_PATH", ""),
        "/app/data/products.db",
        "/data/products.db",
        os.path.expanduser("~/.gemini/antigravity-ide/brain/a63699dd-a0d8-45c2-92f8-5447bbe7d030/scratch/products.db"),
        "data/products.db",
    ]
    for p in candidates:
        if p and os.path.exists(p):
            return p
    return None


def get_product_from_db(url: str) -> Optional[Dict[str, Any]]:
    """Fetch product details directly from local SQLite database in < 1ms."""
    db_path = _get_db_path()
    if not db_path:
        return None
    try:
        conn = sqlite3.connect(db_path, timeout=1.0)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        clean_url = url.split("?")[0].rstrip("/")
        c.execute("SELECT * FROM products WHERE url = ? OR url = ? LIMIT 1", (url, clean_url))
        row = c.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        return None


def search_products_in_db(query: str, limit: int = 4) -> List[Dict[str, Any]]:
    """Full-text search in local SQLite products catalog in < 5ms."""
    db_path = _get_db_path()
    if not db_path:
        return []
    try:
        conn = sqlite3.connect(db_path, timeout=1.0)
        conn.row_factory = sqlite3.Row
        c = conn.cursor()
        clean_q = re.sub(r'[^\w\s]', ' ', query).strip()
        stop_words = {"في", "من", "عن", "على", "كم", "وش", "ايش", "ما", "هو", "هي", "مواصفات", "مميزات", "سعر", "اسعار", "تفاصيل", "هل", "عندكم", "ممكن"}
        words = [w for w in clean_q.split() if len(w) > 1 and w not in stop_words]
        if not words:
            words = [w for w in clean_q.split() if len(w) > 1]
        if not words:
            conn.close()
            return []

        fts_q = " OR ".join([f'"{w}"*' for w in words])
        results = []
        try:
            c.execute(
                """
                SELECT p.id, p.name, p.price, p.old_price, p.discount, p.category, p.description, p.url
                FROM products_fts f
                JOIN products p ON f.rowid = p.id
                WHERE products_fts MATCH ?
                ORDER BY rank
                LIMIT ?;
                """,
                (fts_q, limit),
            )
            results = [dict(r) for r in c.fetchall()]
        except Exception:
            results = []

        if not results:
            like_terms = [f"%{w}%" for w in words]
            where_clauses = " OR ".join(["name LIKE ? OR category LIKE ? OR description LIKE ?" for _ in like_terms])
            params = []
            for t in like_terms:
                params.extend([t, t, t])
            params.append(limit)
            c.execute(
                f"SELECT id, name, price, old_price, discount, category, description, url FROM products WHERE {where_clauses} LIMIT ?;",
                params,
            )
            results = [dict(r) for r in c.fetchall()]

        conn.close()
        return results
    except Exception:
        return []


def scrape_url(url: str, max_chars: int = 4000) -> Tuple[str, str]:
    """Scrape a URL and return a clean markdown excerpt and spoken summary with caching."""
    if not is_domain_allowed(url):
        allowed_str = ", ".join(ALLOWED_DOMAINS)
        return (
            f"Access restricted: Scraping is only allowed for domain(s): {allowed_str}",
            f"Sorry, I am only authorized to access content from {allowed_str}.",
        )

    if not url.startswith("http://") and not url.startswith("https://"):
        url = f"https://{url}"

    # Check local cache first for sub-millisecond response!
    cache_key = f"scrape:{url}"
    cached = get_from_cache(cache_key)
    if cached:
        return cached

    # Check local SQLite DB first (instant sub-millisecond retrieval)
    prod = get_product_from_db(url)
    if prod:
        discount_text = f" (وفر {prod['discount']})" if prod.get('discount') else ""
        old_price_text = f" بدلاً من {prod['old_price']}" if prod.get('old_price') and prod['old_price'] != prod['price'] else ""
        full_text = (
            f"المنتج: {prod['name']}\n"
            f"السعر الحالي: {prod['price']}{old_price_text}{discount_text}\n"
            f"الفئة: {prod['category']}\n"
            f"المواصفات والمميزات:\n{prod['description']}\n"
            f"الرابط: {prod['url']}"
        )
        spoken = f"{prod['name']} بسعر {prod['price']}{discount_text}. {prod['description'][:150]}"
        res = (full_text, spoken)
        put_in_cache(cache_key, res)
        return res

    payload = {
        "url": url,
        "formats": ["markdown"],
        "onlyMainContent": True,
        "maxAge": 3600000,  # Utilize Firecrawl 1-hour internal cache for 5x speed
        "waitFor": 0,       # No artificial delay
        "timeout": 8000,    # 8 seconds fast timeout
    }

    try:
        data = _make_request("/v1/scrape", payload)
    except urllib.error.HTTPError as he:
        # Fallback to v0 if v1 endpoint isn't supported
        if he.code == 404:
            data = _make_request("/v0/scrape", payload)
        else:
            raise

    # Response parsing
    scrape_data = data.get("data", {})
    if isinstance(scrape_data, list) and scrape_data:
        scrape_data = scrape_data[0]

    markdown = scrape_data.get("markdown", "") or scrape_data.get("content", "")
    metadata = scrape_data.get("metadata", {})
    title = metadata.get("title", "") or scrape_data.get("title", "")

    if not markdown:
        res = ("No text content found on the page.", "The webpage had no readable content.")
        put_in_cache(cache_key, res)
        return res

    # Clean markdown thoroughly for minimal token overhead and fast TTS
    cleaned_text = clean_markdown_for_voice(markdown)
    excerpt = cleaned_text[:max_chars]
    if len(cleaned_text) > max_chars:
        excerpt += "..."

    spoken = f"{title}: {excerpt[:350]}" if title else f"{excerpt[:350]}"
    res = (excerpt, spoken)
    put_in_cache(cache_key, res)
    return res


# In-memory product directory for instant search and full specifications
_PRODUCT_INDEX: List[Tuple[str, str]] = []


def _load_product_index() -> None:
    """Load all product URLs from reefi.me sitemap into memory for sub-millisecond search."""
    global _PRODUCT_INDEX
    try:
        url = "https://reefi.me/sitemap_products.xml"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            root = ET.fromstring(resp.read())
            prods = []
            for elem in root.iter():
                if elem.tag.endswith("loc") and elem.text and "/products/" in elem.text:
                    u = elem.text.strip()
                    slug = urllib.parse.unquote(u.split("/products/")[-1]).replace("-", " ")
                    prods.append((slug, u))
            if prods:
                _PRODUCT_INDEX = prods
    except Exception:
        pass


def find_best_product_url(query: str) -> Optional[Tuple[str, str]]:
    """Match a product name or keywords against the in-memory product index."""
    if not _PRODUCT_INDEX:
        _load_product_index()
    if not _PRODUCT_INDEX:
        return None

    q = re.sub(r"[^\w\s]", "", query).lower()
    stop_words = {
        "في", "من", "عن", "على", "كم", "وش", "ايش", "ما", "هو", "هي",
        "مواصفات", "مميزات", "سعر", "اسعار", "تفاصيل", "طقم", "هل", "عندكم"
    }
    words = [w for w in q.split() if len(w) > 1 and w not in stop_words]
    if not words:
        words = [w for w in q.split() if len(w) > 1]
    if not words:
        return None

    best_match = None
    best_score = 0
    for title, u in _PRODUCT_INDEX:
        score = sum(1 for w in words if w in title.lower())
        if score > best_score:
            best_score = score
            best_match = (title, u)

    return best_match if best_score > 0 else None


def search_web(query: str, limit: int = 3) -> Tuple[str, str]:
    """Search products or content on reefi.me and return detailed specifications."""
    cache_key = f"search:{query}:{limit}"
    cached = get_from_cache(cache_key)
    if cached:
        return cached

    # 1. Search local SQLite DB first (instant sub-millisecond retrieval with FTS5)
    hits = search_products_in_db(query, limit=limit)
    if hits:
        formatted_items = []
        spoken_items = []
        for idx, p in enumerate(hits, 1):
            price_info = f"السعر: {p['price']}"
            if p.get('old_price') and p['old_price'] != p['price']:
                price_info += f" (قبل الخصم: {p['old_price']})"
            if p.get('discount'):
                price_info += f" - وفر {p['discount']}"
            formatted_items.append(f"{idx}. {p['name']} ({price_info})\n   المميزات: {p['description'][:200]}\n   الرابط: {p['url']}")
            if idx <= 2:
                spoken_items.append(f"{p['name']} بسعر {p['price']}")
        full_text = "\n\n".join(formatted_items)
        spoken = "من أفضل الخيارات المتوفرة: " + "، و ".join(spoken_items)
        res = (full_text, spoken)
        put_in_cache(cache_key, res)
        return res

    # 2. Match against in-memory product catalog second
    matched = find_best_product_url(query)
    if matched:
        prod_title, prod_url = matched
        excerpt, spoken_summary = scrape_url(prod_url, max_chars=4000)
        full_text = f"المنتج: {prod_title}\nالرابط: {prod_url}\n\nالمواصفات والأسعار والمميزات:\n{excerpt}"
        spoken = f"منتج {prod_title}: {spoken_summary[:300]}"
        res = (full_text, spoken)
        put_in_cache(cache_key, res)
        return res

    # 3. Fallback to Firecrawl search API scoped to allowed domain
    search_q = query
    if ALLOWED_DOMAINS and "site:" not in search_q.lower():
        search_q = f"site:{ALLOWED_DOMAINS[0]} {search_q}"

    payload = {
        "query": search_q,
        "limit": limit,
    }

    try:
        data = _make_request("/v1/search", payload)
    except urllib.error.HTTPError as he:
        if he.code == 404:
            data = _make_request("/v0/search", payload)
        else:
            raise

    results = data.get("data", [])
    if not results and isinstance(data, list):
        results = data

    # Filter results by allowed domains
    if ALLOWED_DOMAINS:
        results = [r for r in results if is_domain_allowed(r.get("url", ""))]

    if not results:
        msg = f"لم يتم العثور على نتائج لـ: {query}"
        res = (msg, msg)
        put_in_cache(cache_key, res)
        return res

    # If top result is a product page, enrich it with full scrape content
    top_url = results[0].get("url", "")
    if "/products/" in top_url:
        top_excerpt, _ = scrape_url(top_url, max_chars=4000)
        top_title = results[0].get("title", "")
        full_text = f"المنتج: {top_title}\nالرابط: {top_url}\n\nالمواصفات الكاملة والمميزات:\n{top_excerpt}"
        spoken = f"بيانات {top_title}: {top_excerpt[:250]}"
        res = (full_text, spoken)
        put_in_cache(cache_key, res)
        return res

    formatted_items = []
    spoken_items = []
    for idx, item in enumerate(results[:limit], 1):
        title = item.get("title", "No Title")
        url = item.get("url", "")
        desc = item.get("description", "") or item.get("markdown", "")
        desc_snippet = clean_markdown_for_voice(desc)[:300]
        formatted_items.append(f"{idx}. {title} ({url})\n   {desc_snippet}")
        if idx <= 2:
            spoken_items.append(f"{title}: {desc_snippet[:100]}")

    full_text = "\n\n".join(formatted_items)
    spoken = "النتائج المتاحة: " + "; ".join(spoken_items)
    res = (full_text, spoken)
    put_in_cache(cache_key, res)
    return res


def _warmup_cache_background() -> None:
    """Pre-warm cache and load product index in background on startup."""
    time.sleep(1)
    _load_product_index()
    popular_urls = [
        "https://reefi.me",
        "https://reefi.me/categories/1675703/خصومات-حقيقية",
        "https://reefi.me/categories/1045941/مودرن",
        "https://reefi.me/categories/1048987/جميع-الارواب",
        "https://reefi.me/categories/1136238/مرتبة-اوى",
        "https://reefi.me/products/مرتبة-اوى-المطورة",
        "https://reefi.me/products/Awa-Mattress",
        "https://reefi.me/products/Modern-bathrobe-petrol-blue",
        "https://reefi.me/products/روب-مودرن-بقبعة-بنفسجي",
        "https://reefi.me/products/طقم-مفرش-الهناء",
        "https://reefi.me/products/بكج-منشفة-كبيرة-وافل",
    ]
    for target in popular_urls:
        try:
            scrape_url(target, max_chars=4000)
        except Exception:
            pass


# Launch background cache warming
threading.Thread(target=_warmup_cache_background, daemon=True).start()


def main() -> None:
    for raw in sys.stdin.buffer:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line.decode("utf-8"))
            method = msg.get("method", "")
            req_id = msg.get("id")
            params = msg.get("params", {})

            if method == "initialize":
                send_response(
                    req_id,
                    {
                        "protocolVersion": "2024-11-05",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "firecrawl", "version": "1.0.0"},
                    },
                )
            elif method == "tools/list":
                send_response(
                    req_id,
                    {
                        "tools": [
                            {
                                "name": "scrape_url",
                                "description": "Scrape and extract clean text and markdown content from any website URL.",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "url": {
                                            "type": "string",
                                            "description": "Full URL of the webpage to scrape (e.g. https://example.com)",
                                        }
                                    },
                                    "required": ["url"],
                                },
                            },
                            {
                                "name": "search_web",
                                "description": "Search the web to find latest news, articles, and answers to questions.",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "query": {
                                            "type": "string",
                                            "description": "Search terms or keywords",
                                        },
                                        "limit": {
                                            "type": "integer",
                                            "description": "Maximum number of results (default 3)",
                                            "default": 3,
                                        },
                                    },
                                    "required": ["query"],
                                },
                            },
                        ]
                    },
                )
            elif method == "tools/call":
                tool_name = params.get("name", "")
                args = params.get("arguments", {})
                if tool_name == "scrape_url":
                    url = args.get("url", "")
                    try:
                        content, spoken = scrape_url(url)
                        send_response(
                            req_id,
                            {
                                "content": [{"type": "text", "text": content}],
                                "structured": {"spoken": spoken},
                            },
                        )
                    except Exception as err:
                        err_msg = f"Failed to scrape webpage {url}: {err}"
                        send_response(
                            req_id,
                            {
                                "content": [{"type": "text", "text": err_msg}],
                                "structured": {"spoken": f"Sorry, I could not fetch that webpage. {err}"},
                            },
                        )
                elif tool_name == "search_web":
                    query = args.get("query", "")
                    limit = int(args.get("limit", 3))
                    try:
                        content, spoken = search_web(query, limit)
                        send_response(
                            req_id,
                            {
                                "content": [{"type": "text", "text": content}],
                                "structured": {"spoken": spoken},
                            },
                        )
                    except Exception as err:
                        err_msg = f"Web search failed: {err}"
                        send_response(
                            req_id,
                            {
                                "content": [{"type": "text", "text": err_msg}],
                                "structured": {"spoken": f"Sorry, web search is currently unavailable. {err}"},
                            },
                        )
                else:
                    send_response(req_id, {"content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}]})
            elif method == "notifications/initialized":
                pass
            else:
                if req_id is not None:
                    send_response(req_id, {})
        except Exception as e:
            sys.stderr.write(f"Error: {e}\n")
            sys.stderr.flush()


if __name__ == "__main__":
    main()
