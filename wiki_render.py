"""
wiki_render.py — Markdown rendering with [[wikilink]] resolution.
"""

import markdown
from markdown.inlinepatterns import InlineProcessor
from markdown.extensions import Extension
import xml.etree.ElementTree as ET
import re

from wiki_links import WIKILINK_PIPED_RE, normalize_page_name


class WikiLinkPattern(InlineProcessor):
    """Convert [[wikilinks]] to HTML links during markdown rendering."""

    def handleMatch(self, m, data):
        raw_target = m.group(1).strip()
        display_text = m.group(2)
        
        target = normalize_page_name(raw_target)
        display = display_text.strip() if display_text else raw_target.strip()
        
        href = f"/{target}"
        el = ET.Element("a")
        el.set("href", href)
        el.set("class", "wikilink")
        el.text = display
        return el, m.start(0), m.end(0)


class WikiLinkExtension(Extension):
    """Markdown extension that processes [[wikilinks]]."""

    def extendMarkdown(self, md):
        pattern = WikiLinkPattern(WIKILINK_PIPED_RE.pattern, md)
        md.inlinePatterns.register(pattern, "wikilink", 175)


def render_markdown(content: str) -> str:
    """Render markdown content to HTML with wiki link support."""
    if not content:
        return ""
    
    ext = WikiLinkExtension()
    md = markdown.Markdown(
        extensions=[
            ext,
            "fenced_code",
            "codehilite",
            "tables",
            "toc",
            "sane_lists",
            "attr_list",
            "def_list",
            "footnotes",
        ]
    )
    html = md.convert(content)
    return html


def strip_markdown(content: str) -> str:
    """Strip markdown formatting for plain text previews."""
    if not content:
        return ""
    # Simple strip — remove headers, bold, italic, links, wikilinks
    text = content
    text = re.sub(r"^#+\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[\[([^\]]+?)(?:\|[^\]]+)?\]\]", r"\1", text)
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    text = re.sub(r"`(.+?)`", r"\1", text)
    return text.strip()