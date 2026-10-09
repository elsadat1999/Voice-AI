#!/usr/bin/env python3
"""High-performance local SQLite Product Catalog MCP Server for Voice AI.

Reads product data, prices, and specifications directly from local SQLite
database with sub-millisecond FTS5 search. Completely offline — zero external
network calls or scraping to guarantee ultra-low telephony latency (< 5ms).
"""

import json
import logging
import os
import re
import sqlite3
import sys
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [catalog_mcp] %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
)
logger = logging.getLogger("catalog_mcp_server")


def send_response(req_id: Any, result: Any) -> None:
    """Send JSON-RPC 2.0 response via newline-delimited JSON."""
    msg = {"jsonrpc": "2.0", "id": req_id, "result": result}
    body = json.dumps(msg, ensure_ascii=False)
    sys.stdout.buffer.write((body + "\n").encode("utf-8"))
    sys.stdout.buffer.flush()


def _get_db_candidates() -> List[str]:
    """Get prioritized list of candidate database paths."""
    candidates = [
        os.environ.get("CATALOG_DB_PATH", "").strip(),
        os.environ.get("REEFI_DB_PATH", "").strip(),
        "/app/data/products.db",
        "/data/products.db",
        os.path.join(os.path.dirname(__file__), "../../data/products.db"),
        os.path.join(os.path.dirname(__file__), "../../../data/products.db"),
        "data/products.db",
        "/app/data/catalog.db",
        "data/catalog.db",
    ]
    return [p for p in candidates if p]


_DB_CONN: Optional[sqlite3.Connection] = None
_ACTIVE_DB_PATH: Optional[str] = None


def get_db_connection() -> Optional[sqlite3.Connection]:
    """Return an open SQLite connection with read-only pragmas."""
    global _DB_CONN, _ACTIVE_DB_PATH

    if _DB_CONN is not None:
        try:
            _DB_CONN.execute("SELECT 1;")
            return _DB_CONN
        except Exception:
            try:
                _DB_CONN.close()
            except Exception:
                pass
            _DB_CONN = None

    candidates = _get_db_candidates()
    for path in candidates:
        abs_path = os.path.abspath(path)
        if os.path.exists(abs_path):
            try:
                # Open read-only URI if supported, fallback to normal connect
                try:
                    conn = sqlite3.connect(f"file:{abs_path}?mode=ro", uri=True, timeout=1.0)
                except Exception:
                    conn = sqlite3.connect(abs_path, timeout=1.0)
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA query_only = ON;")
                conn.execute("PRAGMA busy_timeout = 2000;")
                _DB_CONN = conn
                _ACTIVE_DB_PATH = abs_path
                logger.info("Connected to catalog database at: %s", abs_path)
                return _DB_CONN
            except Exception as e:
                logger.warning("Failed opening database at %s: %s", abs_path, e)

    return None


def _clean_arabic_text(text: str) -> str:
    """Normalize text for voice synthesis and remove markdown/URL artifacts."""
    if not text:
        return ""
    # Strip HTML tags
    clean = re.sub(r"<[^>]+>", "", text)
    # Strip URLs
    clean = re.sub(r"https?://\S+", "", clean)
    # Strip markdown links [label](url) -> label
    clean = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", clean)
    # Strip special markdown formatting symbols
    clean = re.sub(r"[*_~`#>]", "", clean)
    # Normalize whitespaces
    return " ".join(clean.split()).strip()


def _format_spoken_product(p: Dict[str, Any]) -> str:
    """Format product for natural Arabic voice playback."""
    name = p.get("name", "").strip()
    price = p.get("price", "").strip()
    old_price = p.get("old_price", "").strip()
    discount = p.get("discount", "").strip()
    desc = _clean_arabic_text(p.get("description", ""))

    spoken_parts = [name]
    if price:
        if discount and old_price and old_price != price:
            spoken_parts.append(f"بسعر {price} بدلاً من {old_price}، مع خصم {discount}")
        else:
            spoken_parts.append(f"بسعر {price}")

    if desc:
        # Take first crisp sentence or first 100 characters
        first_clause = re.split(r"[.\n،]", desc)[0].strip()
        if len(first_clause) > 10:
            spoken_parts.append(first_clause[:100])

    return ". ".join(spoken_parts)


def search_products(query: str, limit: int = 3) -> Tuple[str, str]:
    """Search products in local SQLite DB using FTS5 and LIKE fallback."""
    conn = get_db_connection()
    if not conn:
        msg = "قاعدة بيانات المنتجات غير متوفرة حالياً على الخادم."
        return msg, msg

    clean_q = re.sub(r"[^\w\s]", " ", query).strip()
    stop_words = {
        "في", "من", "عن", "على", "كم", "وش", "ايش", "ما", "هو", "هي", "بكم",
        "مواصفات", "مميزات", "سعر", "اسعار", "تفاصيل", "هل", "عندكم", "ممكن",
        "ابغى", "اريد", "ابي", "طقم", "واحد", "حبة", "نوع", "أنواع", "ال"
    }
    words = [w for w in clean_q.split() if len(w) > 1 and w not in stop_words]
    if not words:
        words = [w for w in clean_q.split() if len(w) > 1]
    if not words:
        words = [clean_q] if clean_q else []

    if not words:
        return "يرجى تحديد اسم المنتج المطلوب للبحث عنه.", "يرجى تحديد اسم المنتج أو الفئة المطلوبة."

    limit = max(1, min(limit, 8))
    results: List[Dict[str, Any]] = []

    # 1. High-speed FTS5 search (< 2ms)
    fts_q = " OR ".join([f'"{w}"*' for w in words])
    try:
        cursor = conn.execute(
            """
            SELECT p.id, p.name, p.price, p.old_price, p.discount, p.category, p.description, p.url, p.in_stock
            FROM products_fts f
            JOIN products p ON f.rowid = p.id
            WHERE products_fts MATCH ?
            ORDER BY rank
            LIMIT ?;
            """,
            (fts_q, limit),
        )
        results = [dict(r) for r in cursor.fetchall()]
    except Exception as e:
        logger.debug("FTS5 match failed (%s), falling back to LIKE", e)
        results = []

    # 2. LIKE fallback across name, category, and description (< 5ms)
    if not results:
        like_terms = [f"%{w}%" for w in words]
        where_clauses = " OR ".join(["name LIKE ? OR category LIKE ? OR description LIKE ?" for _ in like_terms])
        params: List[Any] = []
        for t in like_terms:
            params.extend([t, t, t])
        params.append(limit)
        try:
            cursor = conn.execute(
                f"""
                SELECT id, name, price, old_price, discount, category, description, url, in_stock
                FROM products
                WHERE {where_clauses}
                LIMIT ?;
                """,
                params,
            )
            results = [dict(r) for r in cursor.fetchall()]
        except Exception as e:
            logger.error("LIKE search failed: %s", e)
            results = []

    if not results:
        not_found_msg = f"لم يتم العثور على نتائج مطابقة لـ '{query}' في المنتجات المتوفرة."
        not_found_spoken = "عذراً، لم أجد هذا المنتج في قائمة المنتجات المتوفرة حالياً. هل تحب أبحث لك عن نوع آخر؟"
        return not_found_msg, not_found_spoken

    # Format structured content for LLM
    text_blocks = []
    spoken_summaries = []
    for idx, p in enumerate(results, 1):
        price_line = f"السعر: {p.get('price') or 'غير محدد'}"
        if p.get("old_price") and p["old_price"] != p.get("price"):
            price_line += f" (قبل الخصم: {p['old_price']})"
        if p.get("discount"):
            price_line += f" - وفر {p['discount']}"

        stock_status = "متوفر" if p.get("in_stock", 1) else "غير متوفر حالياً"
        desc_clean = _clean_arabic_text(p.get("description", ""))[:200]

        text_blocks.append(
            f"{idx}. {p.get('name')}\n"
            f"   {price_line} | الحالة: {stock_status}\n"
            f"   الفئة: {p.get('category') or 'عام'}\n"
            f"   المميزات: {desc_clean}\n"
            f"   الرابط: {p.get('url') or ''}"
        )

        if idx <= 2:
            spoken_summaries.append(_format_spoken_product(p))

    full_text = "\n\n".join(text_blocks)
    if len(spoken_summaries) == 1:
        spoken = f"متوفر لدينا {spoken_summaries[0]}."
    else:
        spoken = f"متوفر خيارات منها: {spoken_summaries[0]}. وأيضاً: {spoken_summaries[1]}."

    return full_text, spoken


def get_product_details(product_name_or_id: str) -> Tuple[str, str]:
    """Retrieve complete product specifications and attributes from SQLite."""
    conn = get_db_connection()
    if not conn:
        msg = "قاعدة بيانات المنتجات غير متوفرة حالياً."
        return msg, msg

    param = product_name_or_id.strip()
    row = None

    # Match by ID if numeric
    if param.isdigit():
        row = conn.execute("SELECT * FROM products WHERE id = ? LIMIT 1;", (int(param),)).fetchone()

    # Match by exact URL
    if not row and ("http://" in param or "https://" in param):
        clean_u = param.split("?")[0].rstrip("/")
        row = conn.execute("SELECT * FROM products WHERE url = ? OR url = ? LIMIT 1;", (param, clean_u)).fetchone()

    # Match by exact or partial name
    if not row:
        row = conn.execute("SELECT * FROM products WHERE name = ? LIMIT 1;", (param,)).fetchone()
    if not row:
        row = conn.execute("SELECT * FROM products WHERE name LIKE ? LIMIT 1;", (f"%{param}%",)).fetchone()

    if not row:
        not_found = f"لم يتم العثور على تفاصيل للمنتج: '{product_name_or_id}'."
        return not_found, "عذراً، لم أجد تفاصيل هذا المنتج في قاعدة البيانات."

    p = dict(row)
    desc = _clean_arabic_text(p.get("description", ""))
    price_info = f"{p.get('price') or ''}"
    if p.get("old_price") and p["old_price"] != p.get("price"):
        price_info += f" بدلاً من {p['old_price']}"
    if p.get("discount"):
        price_info += f" (وفر {p['discount']})"

    full_text = (
        f"اسم المنتج: {p.get('name')}\n"
        f"السعر: {price_info}\n"
        f"الفئة: {p.get('category') or 'غير مصنف'}\n"
        f"الحالة: {'متوفر' if p.get('in_stock', 1) else 'نفد من المخزون'}\n"
        f"المواصفات الكاملة:\n{desc}\n"
        f"الرابط: {p.get('url') or ''}"
    )

    spoken = f"{p.get('name')} بسعر {p.get('price')}. {desc[:150]}"
    return full_text, spoken


def main() -> None:
    # CLI test utility: python3 catalog_mcp_server.py --test "مرتبة"
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        query = sys.argv[2] if len(sys.argv) > 2 else "مرتبة"
        text, spoken = search_products(query)
        print("=== TEXT OUTPUT ===")
        print(text)
        print("\n=== SPOKEN OUTPUT ===")
        print(spoken)
        return

    # MCP stdio JSON-RPC loop
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
                        "serverInfo": {"name": "catalog", "version": "1.0.0"},
                    },
                )
            elif method == "tools/list":
                send_response(
                    req_id,
                    {
                        "tools": [
                            {
                                "name": "search_products",
                                "description": "ابحث في كتالوج وقاعدة بيانات المنتجات المحلية عن الأسعار، الخصومات، المواصفات والتوفر (Search local catalog database).",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "query": {
                                            "type": "string",
                                            "description": "اسم المنتج أو الكلمات المفتاحية (مثال: مرتبة، روب حمام، طقم مفرش، منشفة)",
                                        },
                                        "limit": {
                                            "type": "integer",
                                            "description": "أقصى عدد للنتائج (الافتراضي 3)",
                                            "default": 3,
                                        },
                                    },
                                    "required": ["query"],
                                },
                            },
                            {
                                "name": "get_product_details",
                                "description": "احصل على المواصفات والأسعار الدقيقة لمنتج محدد من قاعدة البيانات المحلية (Get full product details).",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "product_name_or_id": {
                                            "type": "string",
                                            "description": "اسم المنتج أو المعرف الخاص به",
                                        },
                                    },
                                    "required": ["product_name_or_id"],
                                },
                            },
                        ]
                    },
                )
            elif method == "tools/call":
                tool_name = params.get("name", "")
                args = params.get("arguments", {})
                if tool_name == "search_products":
                    query = args.get("query", "")
                    limit = int(args.get("limit", 3))
                    content, spoken = search_products(query, limit)
                    send_response(
                        req_id,
                        {
                            "content": [{"type": "text", "text": content}],
                            "structured": {"spoken": spoken},
                        },
                    )
                elif tool_name == "get_product_details":
                    prod_name = args.get("product_name_or_id", "")
                    content, spoken = get_product_details(prod_name)
                    send_response(
                        req_id,
                        {
                            "content": [{"type": "text", "text": content}],
                            "structured": {"spoken": spoken},
                        },
                    )
                else:
                    send_response(
                        req_id,
                        {"content": [{"type": "text", "text": f"Unknown tool: {tool_name}"}]},
                    )
            elif method == "notifications/initialized":
                pass
            else:
                if req_id is not None:
                    send_response(req_id, {})
        except Exception as e:
            sys.stderr.write(f"Catalog MCP Error: {e}\n")
            sys.stderr.flush()


if __name__ == "__main__":
    main()
