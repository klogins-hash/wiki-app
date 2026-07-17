"""
wiki_app.py — AI-first wiki server.
FastAPI app optimized for AI agent editing and maintenance.
Web UI is read-only for humans; all writes go through the API.
"""

import os
import shutil
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# Add parent dir to path for module imports
sys.path.insert(0, str(Path(__file__).parent))
from wiki_repo import WikiRepo
from wiki_links import build_graph, get_local_graph, get_backlinks, extract_wikilinks, normalize_page_name
from wiki_render import render_markdown, strip_markdown

# ── config ─────────────────────────────────────────────────────

WIKI_DIR = Path(os.environ.get("WIKI_VOLUME", Path(__file__).parent / "wiki"))
SEED_WIKI_DIR = Path(__file__).parent / "seed_wiki"
STATIC_DIR = Path(__file__).parent / "static"
TEMPLATES_DIR = Path(__file__).parent / "templates"

# ── app setup ──────────────────────────────────────────────────

app = FastAPI(
    title="AI Wiki",
    description="Git-backed markdown wiki optimized for AI agent editing. All writes are versioned.",
    version="0.1.0",
)

# Static files
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Templates
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Wiki repo
wiki = WikiRepo(WIKI_DIR)


# ── Pydantic models ────────────────────────────────────────────

class PageCreate(BaseModel):
    content: str
    author: str = "ai-agent"
    message: str = ""


class PageUpdate(BaseModel):
    content: str
    author: str = "ai-agent"
    message: str = ""


class BatchOperation(BaseModel):
    operations: list[dict]  # [{action, page, content, author, message}]


# ══════════════════════════════════════════════════════════════
# AI AGENT API (write-oriented)
# ══════════════════════════════════════════════════════════════

@app.get("/api/pages")
async def api_list_pages(
    search: Optional[str] = Query(None),
    include_content: bool = Query(False),
):
    """List all pages. Optional text search and content inclusion."""
    if search:
        pages = wiki.search_pages(search)
    else:
        pages = wiki.list_pages()

    if include_content:
        for p in pages:
            p["content"] = wiki.get_page(p["name"])

    return {"pages": pages, "count": len(pages)}


@app.get("/api/pages/{path:path}")
async def api_get_page(path: str):
    """Get a page's raw markdown content."""
    # Normalize: remove trailing .md if present
    if path.endswith(".md"):
        path = path[:-3]
    content = wiki.get_page(path)
    if content is None:
        raise HTTPException(404, f"Page '{path}' not found")
    
    links = extract_wikilinks(content)
    backlinks = get_backlinks(WIKI_DIR, path)
    
    return {
        "name": path,
        "content": content,
        "title": wiki._extract_title(content) or path.split("/")[-1],
        "links": links,
        "backlinks": backlinks,
        "word_count": len(content.split()),
    }


@app.put("/api/pages/{path:path}")
async def api_create_or_update_page(path: str, body: PageUpdate):
    """Create or update a page. Returns the commit SHA."""
    if path.endswith(".md"):
        path = path[:-3]
    
    sha = wiki.save_page(
        path,
        body.content,
        author=body.author or "ai-agent",
        message=body.message or "",
    )
    return {
        "status": "ok",
        "page": path,
        "commit": sha,
        "author": body.author or "ai-agent",
    }


@app.post("/api/pages/{path:path}")
async def api_create_page(path: str, body: PageCreate):
    """Create a new page (alias for PUT, but rejects if exists)."""
    if path.endswith(".md"):
        path = path[:-3]
    existing = wiki.get_page(path)
    if existing is not None:
        raise HTTPException(409, f"Page '{path}' already exists. Use PUT to update.")
    
    sha = wiki.save_page(
        path,
        body.content,
        author=body.author or "ai-agent",
        message=body.message or "",
    )
    return {
        "status": "created",
        "page": path,
        "commit": sha,
    }


@app.delete("/api/pages/{path:path}")
async def api_delete_page(path: str, author: str = Query("ai-agent")):
    """Delete a page."""
    if path.endswith(".md"):
        path = path[:-3]
    if not wiki.delete_page(path, author=author):
        raise HTTPException(404, f"Page '{path}' not found")
    return {"status": "deleted", "page": path}


@app.get("/api/pages/{path:path}/history")
async def api_page_history(path: str):
    """Get version history for a page."""
    if path.endswith(".md"):
        path = path[:-3]
    history = wiki.get_history(path)
    if not history:
        raise HTTPException(404, f"Page '{path}' not found or has no history")
    return {"page": path, "history": history, "count": len(history)}


@app.get("/api/pages/{path:path}/version/{commit_sha}")
async def api_page_version(path: str, commit_sha: str):
    """Get page content at a specific version."""
    if path.endswith(".md"):
        path = path[:-3]
    content = wiki.get_version(path, commit_sha)
    if content is None:
        raise HTTPException(404, f"Version not found for page '{path}' at {commit_sha}")
    return {
        "page": path,
        "commit": commit_sha,
        "content": content,
    }


@app.post("/api/pages/{path:path}/revert/{commit_sha}")
async def api_revert_page(path: str, commit_sha: str, author: str = Query("ai-agent")):
    """Revert a page to a previous version."""
    if path.endswith(".md"):
        path = path[:-3]
    new_sha = wiki.revert_to(path, commit_sha, author=author)
    if new_sha is None:
        raise HTTPException(404, f"Cannot revert — page or version not found")
    return {
        "status": "reverted",
        "page": path,
        "reverted_to": commit_sha,
        "new_commit": new_sha,
    }


@app.get("/api/pages/{path:path}/diff")
async def api_page_diff(
    path: str,
    from_sha: str = Query(),
    to_sha: str = Query(),
):
    """Get diff between two versions of a page."""
    if path.endswith(".md"):
        path = path[:-3]
    diff = wiki.diff_versions(path, from_sha, to_sha)
    return {
        "page": path,
        "from": from_sha,
        "to": to_sha,
        "diff": diff,
    }


# ── batch operations ───────────────────────────────────────────

@app.post("/api/batch")
async def api_batch(body: BatchOperation):
    """Execute multiple operations atomically (each is a separate commit).
    
    Operations: [{action: "create|update|delete", page: "...", content: "...", author: "...", message: "..."}]
    """
    results = []
    for op in body.operations:
        page = op.get("page", "").rstrip(".md")
        action = op.get("action", "update")
        author = op.get("author", "ai-agent")
        message = op.get("message", "")
        
        try:
            if action == "delete":
                ok = wiki.delete_page(page, author=author)
                if not ok:
                    results.append({"page": page, "status": "error", "error": "not found"})
                else:
                    results.append({"page": page, "status": "deleted"})
            else:
                content = op.get("content", "")
                sha = wiki.save_page(page, content, author=author, message=message)
                results.append({"page": page, "status": "ok", "commit": sha})
        except Exception as e:
            results.append({"page": page, "status": "error", "error": str(e)})
    
    return {"results": results, "count": len(results)}


# ── knowledge graph API ────────────────────────────────────────

@app.get("/api/graph")
async def api_graph():
    """Get the full knowledge graph (nodes + edges) for visualization."""
    graph = build_graph(WIKI_DIR)
    return graph


@app.get("/api/graph/local/{path:path}")
async def api_local_graph(path: str, depth: int = Query(1, ge=1, le=3)):
    """Get the local subgraph around a page."""
    if path.endswith(".md"):
        path = path[:-3]
    return get_local_graph(WIKI_DIR, path, depth=depth)


@app.get("/api/backlinks/{path:path}")
async def api_backlinks(path: str):
    """Get all pages that link to this page."""
    if path.endswith(".md"):
        path = path[:-3]
    return {"page": path, "backlinks": get_backlinks(WIKI_DIR, path)}


# ── repo info ──────────────────────────────────────────────────

@app.get("/api/info")
async def api_info():
    """Get wiki metadata and stats."""
    pages = wiki.list_pages()
    graph = build_graph(WIKI_DIR)
    return {
        "name": "AI Wiki",
        "version": "0.1.0",
        "total_pages": len(pages),
        "total_commits": sum(len(wiki.get_history(p["name"])) for p in pages[:10]),  # approximate
        "stats": graph["stats"],
        "wiki_dir": str(WIKI_DIR),
    }


# ══════════════════════════════════════════════════════════════
# HUMAN WEB UI (read-only)
# ══════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
async def web_index(request: Request):
    """List all pages with graph overview."""
    pages = wiki.list_pages()
    graph = build_graph(WIKI_DIR)
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "pages": pages,
            "stats": graph["stats"],
            "title": "AI Wiki",
        },
    )


@app.get("/{path:path}", response_class=HTMLResponse)
async def web_page(request: Request, path: str):
    """View a rendered wiki page."""
    # Strip .md suffix
    if path.endswith(".md"):
        path = path[:-3]
    
    # Check if it's a static file
    static_file = STATIC_DIR / path
    if static_file.exists() and not path.endswith(".html"):
        return PlainTextResponse(static_file.read_text())

    content = wiki.get_page(path)
    if content is None:
        raise HTTPException(404, f"Page '{path}' not found")

    html = render_markdown(content)
    title = wiki._extract_title(content) or path.split("/")[-1]
    history = wiki.get_history(path, max_count=5)
    backlinks = get_backlinks(WIKI_DIR, path)
    links = extract_wikilinks(content)
    local_graph = get_local_graph(WIKI_DIR, path, depth=1)

    return templates.TemplateResponse(
        "page.html",
        {
            "request": request,
            "path": path,
            "title": title,
            "content": html,
            "history": history,
            "backlinks": backlinks,
            "links": links,
            "local_graph": local_graph,
            "raw_content": content,
        },
    )


@app.get("/{path:path}/history", response_class=HTMLResponse)
async def web_history(request: Request, path: str):
    """View full version history of a page."""
    if path.endswith(".md"):
        path = path[:-3]
    content = wiki.get_page(path)
    if content is None:
        raise HTTPException(404, f"Page '{path}' not found")
    
    history = wiki.get_history(path, max_count=100)
    title = wiki._extract_title(content) or path.split("/")[-1]

    return templates.TemplateResponse(
        "history.html",
        {
            "request": request,
            "path": path,
            "title": title,
            "history": history,
        },
    )


# ── error handlers ─────────────────────────────────────────────

@app.exception_handler(404)
async def not_found(request: Request, exc):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"error": "Not found"}, status_code=404)
    return HTMLResponse(
        "<h1>404 — Page Not Found</h1><p>This wiki page doesn't exist yet.</p><a href='/'>← Back to wiki</a>",
        status_code=404,
    )


# ── entry point ────────────────────────────────────────────────

def main():
    import uvicorn
    
    port = int(os.environ.get("PORT", 8080))
    host = os.environ.get("HOST", "0.0.0.0")
    
    # ── seed wiki content on fresh volume ─────────────────────
    if not any(WIKI_DIR.iterdir()):
        print("🌱 Seeding wiki content from seed_wiki/...")
        for item in SEED_WIKI_DIR.iterdir():
            if item.is_file():
                shutil.copy2(item, WIKI_DIR / item.name)
    
    # wiki repo init (handles git init on fresh dirs)
    global wiki
    wiki = WikiRepo(WIKI_DIR)
    
    pages = wiki.list_pages()
    
    print(f"╔══════════════════════════════════════════╗")
    print(f"║     AI Wiki — Agent-First Wiki           ║")
    print(f"║━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━║")
    print(f"║  Web UI:  http://{host}:{port}            ║")
    print(f"║  API:     http://{host}:{port}/api/       ║")
    print(f"║  Graph:   http://{host}:{port}/api/graph  ║")
    print(f"║━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━║")
    print(f"║  Pages: {len(pages) if pages else 0}  |  "
          f"Git: {WIKI_DIR}/.git  ║")
    print(f"╚══════════════════════════════════════════╝")
    
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()