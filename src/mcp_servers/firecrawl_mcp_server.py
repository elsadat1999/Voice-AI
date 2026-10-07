#!/usr/bin/env python3
"""Firecrawl MCP server for Voice AI (scraping, crawling, and web search)."""

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, Optional, Tuple

FIRECRAWL_API_URL = os.environ.get(
    "FIRECRAWL_API_URL", "http://firecrawl-service.voice-ai.svc.cluster.local:3002"
).rstrip("/")
FIRECRAWL_API_KEY = os.environ.get("FIRECRAWL_API_KEY", "").strip()

# Optional list of comma-separated domains allowed (e.g., "example.com,nassaqapp.com")
def _normalize_domain(raw_val: str) -> str:
    raw_val = raw_val.strip().lower()
    if "://" in raw_val:
        from urllib.parse import urlparse
        return (urlparse(raw_val).netloc or "").split(":")[0]
    return raw_val.split("/")[0].split(":")[0]


ALLOWED_DOMAINS = [
    _normalize_domain(d) for d in os.environ.get("ALLOWED_DOMAINS", "").split(",") if d.strip()
]


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


def scrape_url(url: str, max_chars: int = 1200) -> Tuple[str, str]:
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

    spoken = f"From {title or url}: {excerpt[:250]}" if title else f"{excerpt[:250]}"
    res = (excerpt, spoken)
    put_in_cache(cache_key, res)
    return res


def search_web(query: str, limit: int = 3) -> Tuple[str, str]:
    """Search web using Firecrawl search API and return top results with caching."""
    # Scope search strictly to allowed domain if configured
    if ALLOWED_DOMAINS and "site:" not in query.lower():
        query = f"site:{ALLOWED_DOMAINS[0]} {query}"

    cache_key = f"search:{query}:{limit}"
    cached = get_from_cache(cache_key)
    if cached:
        return cached

    payload = {
        "query": query,
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

    # Filter results by allowed domains if configured
    if ALLOWED_DOMAINS:
        results = [r for r in results if is_domain_allowed(r.get("url", ""))]

    if not results:
        msg = f"No search results found for: {query}"
        res = (msg, msg)
        put_in_cache(cache_key, res)
        return res

    formatted_items = []
    spoken_items = []
    for idx, item in enumerate(results[:limit], 1):
        title = item.get("title", "No Title")
        url = item.get("url", "")
        desc = item.get("description", "") or item.get("markdown", "")
        desc_snippet = clean_markdown_for_voice(desc)[:200]
        formatted_items.append(f"{idx}. {title} ({url})\n   {desc_snippet}")
        if idx <= 2:
            spoken_items.append(f"{title}: {desc_snippet[:80]}")

    full_text = "\n\n".join(formatted_items)
    spoken = "Found the following: " + "; ".join(spoken_items)
    res = (full_text, spoken)
    put_in_cache(cache_key, res)
    return res


def _warmup_cache_background() -> None:
    """Pre-warm cache in background on startup so the first call is instantaneous."""
    time.sleep(1)
    if ALLOWED_DOMAINS:
        target = f"https://{ALLOWED_DOMAINS[0]}"
        try:
            scrape_url(target)
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
