"""Synchronize the crawl metadata for the static blog."""

import argparse
import json
import re
from html import escape
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

SITE = "https://lehaifeng000.github.io"
ROOT = Path(__file__).resolve().parents[1] / "docs"
POST = re.compile(r"posts/[a-z0-9][a-z0-9-]*/index\.html")
BLOCK = re.compile(r"(?ms)^  <!-- Search metadata -->\n.*?^  <!-- End search metadata -->\n")
AUTHOR = {"@type": "Person", "name": "haifeng", "url": "https://github.com/lehaifeng000"}
SITEMAP_NAMESPACE = "http://www.sitemaps.org/schemas/sitemap/0.9"


class Page(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.lang = ""
        self.descriptions = []
        self.headlines = []
        self.links = []
        self.heading = None
        self.feed(html)
        self.close()

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "html":
            self.lang = values.get("lang", "")
        if tag == "a":
            link = values.get("href", "")
            if POST.fullmatch(link):
                self.links.append(link)
        if tag == "h1":
            self.heading = []
        if tag == "meta" and values.get("name") == "description":
            self.descriptions.append(values.get("content", ""))

    def handle_data(self, value):
        if self.heading is not None:
            self.heading.append(value)

    def handle_endtag(self, tag):
        if tag == "h1" and self.heading is not None:
            self.headlines.append(" ".join("".join(self.heading).split()))
            self.heading = None


def page_metadata(path, url, html, is_index):
    page = Page(html)
    if len(page.headlines) != 1 or not page.headlines[0] or not page.lang:
        raise ValueError(f"{path}: expected a language and one main heading")
    if len(page.descriptions) != 1 or not page.descriptions[0].strip():
        raise ValueError(f"{path}: expected one nonempty description")

    schema = {
        "@context": "https://schema.org",
        "@type": "WebSite" if is_index else "BlogPosting",
        "url": url,
        "inLanguage": page.lang,
        "description": page.descriptions[0],
    }
    if is_index:
        schema["name"] = page.headlines[0]
    else:
        schema["headline"] = page.headlines[0]
        schema["author"] = AUTHOR
        schema["mainEntityOfPage"] = {"@type": "WebPage", "@id": url}

    # Escape "<" so text from a heading or description stays inside its script.
    payload = json.dumps(schema, ensure_ascii=False, indent=2).replace("<", "\\u003c")
    return (
        "  <!-- Search metadata -->\n"
        f'  <link rel="canonical" href="{escape(url, quote=True)}">\n'
        '  <script type="application/ld+json">\n'
        + "\n".join("  " + line for line in payload.splitlines())
        + "\n  </script>\n  <!-- End search metadata -->\n"
    )


def build():
    index = ROOT / "index.html"
    entries = dict.fromkeys(Page(index.read_text(encoding="utf-8")).links)
    if not entries:
        raise ValueError("No article links found on the homepage")
    paths = [("index.html", SITE + "/")]
    paths.extend((entry, f"{SITE}/{entry}") for entry in entries)

    files = {}
    sitemap = ET.Element("urlset", xmlns=SITEMAP_NAMESPACE)
    for relative, url in paths:
        path = ROOT / relative
        html = path.read_text(encoding="utf-8")
        base = BLOCK.sub("", html)
        if base.count("</head>") != 1:
            raise ValueError(f"{path}: expected a single head")
        metadata = page_metadata(path, url, base, path == index)
        files[path] = base.replace("</head>", metadata + "</head>", 1)
        ET.SubElement(ET.SubElement(sitemap, "url"), "loc").text = url

    ET.indent(sitemap, space="  ")
    files[ROOT / "sitemap.xml"] = (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        + ET.tostring(sitemap, encoding="unicode") + "\n"
    )
    files[ROOT / "robots.txt"] = f"User-agent: *\nAllow: /\n\nSitemap: {SITE}/sitemap.xml\n"
    return files, len(paths)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Report stale files without writing")
    args = parser.parse_args()
    try:
        files, pages = build()
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")
    updated = 0
    for path, content in files.items():
        if path.is_file() and path.read_text(encoding="utf-8") == content:
            continue
        updated += 1
        if args.check:
            print(f"Stale: {path.relative_to(ROOT)}")
        else:
            path.write_text(content, encoding="utf-8", newline="\n")
    if args.check and updated:
        return 1
    print(f"{pages} pages checked. {updated} files updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
