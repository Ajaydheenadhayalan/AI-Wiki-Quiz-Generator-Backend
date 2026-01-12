import requests
from bs4 import BeautifulSoup

DESKTOP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

MOBILE_HEADERS = {
    **DESKTOP_HEADERS,
    "User-Agent": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 "
        "Mobile/15E148 Safari/604.1"
    ),
}


def _fetch(url: str, headers: dict) -> str:
    resp = requests.get(url, headers=headers, timeout=20, allow_redirects=True)
    resp.raise_for_status()
    return resp.text


def _extract(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")

    # Title
    title_el = soup.find("h1", id="firstHeading") or soup.find("h1")
    title_text = title_el.get_text(strip=True) if title_el else "Untitled"

    # Main content area (desktop or mobile)
    content_div = (
        soup.find(id="mw-content-text")
        or soup.select_one("div.mw-parser-output")
        or soup.select_one("section.mw-parser-output")
        or soup.find("main")
    )
    if not content_div:
        return title_text, ""

    # Strip reference junk / infobox / edit markers
    for tag in content_div.select(
        "sup.reference, table, .mw-references-wrap, span.mw-editsection, div.reflist"
    ):
        tag.decompose()

    paragraphs = [p.get_text(" ", strip=True) for p in content_div.find_all("p")]
    text = "\n\n".join([p for p in paragraphs if p])
    return title_text, text


def scrape_wikipedia(url: str) -> tuple[str, str, str]:
    """
    Fetch with a real UA; on 403/429, retry using m.wikipedia.org + mobile UA.
    
    Returns:
        tuple: (title, extracted_text, raw_html)
    """
    html = ""
    try:
        html = _fetch(url, DESKTOP_HEADERS)
    except requests.HTTPError as e:
        status = e.response.status_code if e.response is not None else 0
        if status in (403, 429):
            mobile_url = url.replace("https://en.wikipedia.org", "https://m.wikipedia.org")
            html = _fetch(mobile_url, MOBILE_HEADERS)
        else:
            raise
    
    title, text = _extract(html)
    return title, text, html

