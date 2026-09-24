"""Public URLs must agree after repository renames and package releases."""

import json
import re
import tomllib
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import pytest

from erd_generator import __version__

ROOT = Path(__file__).resolve().parents[2]
PROJECT = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]
REPOSITORY = "https://github.com/fightingBald/database-migration-erd"
WEBSITE = "https://fightingbald.github.io/database-migration-erd/"


class Page(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.nodes = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        self.nodes.append((tag, dict(attrs)))


def test_package_metadata_uses_current_repository():
    assert PROJECT["urls"]["Source"] == REPOSITORY
    assert PROJECT["urls"]["Homepage"] == WEBSITE
    for name, url in PROJECT["urls"].items():
        assert url.startswith(WEBSITE if name == "Homepage" else REPOSITORY)


@pytest.mark.parametrize(
    "path", sorted((ROOT / "site").rglob("*.html")), ids=lambda path: path.name
)
def test_public_pages_have_consistent_canonical_urls_and_local_links(path):
    relative = path.relative_to(ROOT / "site").as_posix()
    expected = WEBSITE if relative == "index.html" else WEBSITE + relative
    page = Page(path.read_text())
    assert ("link", {"rel": "canonical", "href": expected}) in page.nodes
    assert ("meta", {"property": "og:url", "content": expected}) in page.nodes
    assert ("meta", {"name": "robots", "content": "index,follow"}) in page.nodes
    assert sum(tag == "h1" for tag, _ in page.nodes) == 1
    for tag, attrs in page.nodes:
        if tag == "img":
            assert attrs.get("alt")
        url = attrs.get("href", attrs.get("src", ""))
        if not url:
            continue
        parsed = urlsplit(urljoin(expected, url))
        if parsed.netloc == "fightingbald.github.io":
            assert parsed.path.startswith("/database-migration-erd/")
            local = parsed.path.removeprefix("/database-migration-erd/")
            if not local.startswith("assets/"):
                target = ROOT / "site" / (local or "index.html")
                assert target.is_file(), url
                if parsed.fragment:
                    assert any(
                        attrs.get("id") == parsed.fragment
                        for _, attrs in Page(target.read_text()).nodes
                    ), url
        elif parsed.netloc == "github.com" and parsed.path.startswith("/fightingBald/"):
            assert (
                parsed.path == "/fightingBald/database-migration-erd"
                or parsed.path.startswith("/fightingBald/database-migration-erd/")
            ), url


def test_sitemap_and_download_metadata_match_published_pages():
    sitemap = ET.parse(ROOT / "site/sitemap.xml")
    actual = {node.text for node in sitemap.findall(".//{*}loc")}
    assert actual == {
        WEBSITE,
        WEBSITE + "guides/migrations-to-erd.html",
        WEBSITE + "guides/ci-docusaurus.html",
    }
    source = (ROOT / "site/index.html").read_text()
    script = re.search(
        r'<script type="application/ld\+json">(.*?)</script>', source, re.S
    )
    assert script is not None
    data = json.loads(script[1])
    assert data["name"] == "Database Migration ERD"
    assert data["url"] == WEBSITE
    assert data["softwareVersion"] == __version__
    assert data["downloadUrl"] == f"{REPOSITORY}/releases/tag/v{__version__}"
    wheel = f"{REPOSITORY}/releases/download/v{__version__}/migration_erd-{__version__}-py3-none-any.whl"
    assert wheel in source
    assert wheel in (ROOT / "README.md").read_text()
