import re

import httpx
import logfire
import markdownify


def enrich_urls(text: str) -> dict:
    """
    Extract URLs from text, fetch each with httpx (timeout=10s),
    convert HTML to markdown via markdownify, cap total at 20KB.
    Returns dict with key 'url_content' (str).
    Best-effort: failed URLs are logged and skipped.
    """
    urls = re.findall(r"https?://\S+", text)
    parts = []
    total = 0
    for url in urls:
        try:
            resp = httpx.get(
                url,
                timeout=10,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            md = markdownify.markdownify(resp.text)
            if total + len(md) > 20_000:
                remaining = 20_000 - total
                parts.append(md[:remaining] + "...[truncated at 20KB]")
                total = 20_000
                logfire.info(
                    "enrichment.url_fetched",
                    url=url,
                    status_code=resp.status_code,
                    content_length=len(md),
                    truncated=True,
                )
                break
            parts.append(md)
            total += len(md)
            logfire.info(
                "enrichment.url_fetched",
                url=url,
                status_code=resp.status_code,
                content_length=len(md),
            )
        except Exception as e:
            logfire.warning("enrichment.url_failed", url=url, error=str(e))
            continue
    return {"url_content": "\n\n".join(parts)}
