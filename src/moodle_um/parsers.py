"""HTML parsing helpers used by the domain services."""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from markdownify import markdownify


def soup_of(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def html_to_text(html: str, base_url: str = "") -> str:
    """Convert a Moodle page to readable Markdown-ish text."""
    soup = soup_of(html)
    for tag in soup(
        ["script", "style", "noscript", "svg", "nav", "footer", "iframe"]
    ):
        tag.decompose()
    main = soup.select_one("#region-main") or soup.select_one("main") or soup.body
    if main is None:
        return ""
    for sel in (".breadcrumb", ".drawer", ".activity-navigation", ".usermenu"):
        for tag in main.select(sel):
            tag.decompose()
    for a in main.find_all("a"):
        if a.get_text(" ", strip=True).startswith("Skip "):
            a.decompose()
    if base_url:
        for a in main.find_all("a", href=True):
            a["href"] = urljoin(base_url, a["href"])
    text = markdownify(str(main), heading_style="ATX", bullets="-")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def links(html: str, base_url: str) -> list[dict[str, str]]:
    soup = soup_of(html)
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for a in soup.find_all("a", href=True):
        href = urljoin(base_url, a["href"])
        if href in seen or not href.startswith(base_url.split("/", 3)[0]):
            continue
        seen.add(href)
        text = a.get_text(" ", strip=True)
        if text:
            out.append({"text": text, "url": href})
    return out


def find_course_links(html: str, base_url: str) -> list[dict]:
    """Extract course cards from the My courses / dashboard pages."""
    soup = soup_of(html)
    courses: dict[int, dict] = {}
    for a in soup.select('a[href*="course/view.php?id="]'):
        href = urljoin(base_url, a["href"])
        match = re.search(r"[?&]id=(\d+)", href)
        if not match:
            continue
        cid = int(match.group(1))
        if cid == 1:
            continue
        name = a.get_text(" ", strip=True)
        if not name:
            # Sometimes the title is in a sibling heading.
            parent = a.find_parent(["div", "li"])
            if parent:
                heading = parent.find(["h3", "h4", "h5"])
                if heading:
                    name = heading.get_text(" ", strip=True)
        if not name:
            continue
        entry = courses.setdefault(cid, {"id": cid, "name": name, "url": href})
        if not entry["name"]:
            entry["name"] = name
    return sorted(courses.values(), key=lambda c: c["name"].lower())


def parse_breadcrumb(html: str) -> list[str]:
    soup = soup_of(html)
    crumbs = []
    for item in soup.select(".breadcrumb-item"):
        text = item.get_text(" ", strip=True)
        if text and text not in crumbs:
            crumbs.append(text)
    return crumbs


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def soup_text(node) -> str:
    if node is None:
        return ""
    return clean_text(node.get_text(" ", strip=True))
