"""
wiki_links.py — Parse [[wikilinks]] and build a knowledge graph.
Scans all .md files for wiki-style links and builds a directed graph.
"""

import re
from collections import defaultdict
from pathlib import Path
from typing import Optional

WIKILINK_RE = re.compile(r"\[\[([^\[\]]+?)\]\]")
# Matches [[Page Name]] or [[Page Name|Display Text]]
WIKILINK_PIPED_RE = re.compile(r"\[\[([^\[\]]+?)(?:\|([^\[\]]+?))?\]\]")


def extract_wikilinks(content: str) -> list[dict]:
    """Extract all [[wikilinks]] from markdown content.
    
    Returns: [{target: "page-name", display: "Page Name"}] 
    - `target` is the normalized page name (lowercase, hyphens, no .md)
    - `display` is the original text or the pipe text
    """
    links = []
    for match in WIKILINK_PIPED_RE.finditer(content):
        raw_target = match.group(1).strip()
        display_text = match.group(2)
        
        # Normalize to page name
        target = normalize_page_name(raw_target)
        display = display_text.strip() if display_text else raw_target.strip()
        
        links.append({
            "target": target,
            "display": display,
            "raw": match.group(0),
        })
    return links


def normalize_page_name(name: str) -> str:
    """Convert any page reference to canonical form.
    'My Cool Page' → 'my-cool-page'
    'my_page' → 'my-page'
    """
    name = name.strip().lower()
    name = name.replace("_", "-").replace(" ", "-")
    # Remove multiple hyphens
    name = re.sub(r"-+", "-", name)
    # Remove leading/trailing hyphens
    name = name.strip("-")
    return name


def build_graph(wiki_dir: str | Path) -> dict:
    """Scan all markdown files and build the full knowledge graph.
    
    Returns:
    {
        "nodes": [{id, name, title, page_exists}],
        "edges": [{source, target}],
        "stats": {total_pages, total_links, orphaned_pages, broken_links}
    }
    """
    wiki_path = Path(wiki_dir)
    md_files = {str(f.relative_to(wiki_path).with_suffix("")): f 
                for f in wiki_path.rglob("*.md") 
                if f.name != ".gitkeep"}
    
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    broken_links: list[dict] = []
    
    for rel_name, file_path in md_files.items():
        content = file_path.read_text(encoding="utf-8")
        
        # This page as a node
        title = _extract_title(content) or rel_name.split("/")[-1]
        nodes[rel_name] = {
            "id": rel_name,
            "name": rel_name,
            "title": title,
            "page_exists": True,
        }
        
        # Extract links from this page
        links = extract_wikilinks(content)
        for link in links:
            target = link["target"]
            edges.append({
                "source": rel_name,
                "target": target,
            })
            # Create node for target if it doesn't exist as a page
            if target not in nodes:
                nodes[target] = {
                    "id": target,
                    "name": target,
                    "title": target.replace("-", " ").title(),
                    "page_exists": target in md_files,
                }
            if target not in md_files:
                broken_links.append({
                    "source": rel_name,
                    "target": target,
                    "display": link["display"],
                })
    
    # Stats
    existing_pages = {n for n, info in nodes.items() if info["page_exists"]}
    linked_pages = {e["target"] for e in edges}
    orphaned = existing_pages - {e["source"] for e in edges} - linked_pages
    
    return {
        "nodes": list(nodes.values()),
        "edges": edges,
        "stats": {
            "total_pages": len(md_files),
            "total_nodes": len(nodes),
            "total_links": len(edges),
            "orphaned_pages": sorted(orphaned),
            "broken_links": len(broken_links),
            "broken_link_details": broken_links[:50],  # cap at 50
        },
    }


def get_local_graph(wiki_dir: str | Path, page_name: str, depth: int = 1) -> dict:
    """Get the subgraph around a specific page (for local graph view).
    
    Returns nodes and edges within `depth` hops of the given page.
    """
    full = build_graph(wiki_dir)
    
    # BFS from the page
    page_name = normalize_page_name(page_name)
    visited_nodes = {page_name}
    frontier = {page_name}
    
    for _ in range(depth):
        next_frontier = set()
        for edge in full["edges"]:
            if edge["source"] in frontier:
                next_frontier.add(edge["target"])
                visited_nodes.add(edge["target"])
            if edge["target"] in frontier:
                next_frontier.add(edge["source"])
                visited_nodes.add(edge["source"])
        frontier = next_frontier
    
    # Filter edges
    local_edges = [
        e for e in full["edges"]
        if e["source"] in visited_nodes and e["target"] in visited_nodes
    ]
    local_nodes = [n for n in full["nodes"] if n["id"] in visited_nodes]
    
    return {
        "center": page_name,
        "nodes": local_nodes,
        "edges": local_edges,
    }


def get_backlinks(wiki_dir: str | Path, page_name: str) -> list[dict]:
    """Find all pages that link to the given page."""
    page_name = normalize_page_name(page_name)
    graph = build_graph(wiki_dir)
    backlinks = []
    for edge in graph["edges"]:
        if edge["target"] == page_name:
            backlinks.append(edge["source"])
    return sorted(set(backlinks))


def _extract_title(content: str) -> Optional[str]:
    match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
    if match:
        return match.group(1).strip()
    return None