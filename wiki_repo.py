"""
wiki_repo.py — Git-backed markdown file storage.
Every write is a commit. Full version history, diff, revert.
"""

import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import git


class WikiRepo:
    """Manages a Git repo of markdown files as a wiki."""

    def __init__(self, wiki_dir: str | Path):
        self.wiki_dir = Path(wiki_dir).resolve()
        self.wiki_dir.mkdir(parents=True, exist_ok=True)
        self._init_git_repo()

    # ── repo init ──────────────────────────────────────────────

    def _init_git_repo(self):
        """Init or open the Git repo in the wiki directory."""
        git_dir = self.wiki_dir / ".git"
        if git_dir.exists():
            self.repo = git.Repo(self.wiki_dir)
        else:
            self.repo = git.Repo.init(self.wiki_dir)
            # Set user config for commits
            with self.repo.config_writer() as cw:
                cw.set_value("user", "name", "Wiki Bot")
                cw.set_value("user", "email", "wiki@local")
            # Initial commit on empty repo
            gitignore = self.wiki_dir / ".gitkeep"
            gitignore.touch()
            self.repo.index.add([".gitkeep"])
            self.repo.index.commit("🗿 wiki initialized")

    # ── page CRUD ──────────────────────────────────────────────

    def page_path(self, page_name: str) -> Path:
        """Convert a page name to a filesystem path.
        'my-page' or 'my_page' → wiki/my-page.md
        Supports subdirectories via '/' in name.
        """
        # Strip leading/trailing slashes, sanitize
        clean = page_name.strip("/").replace(" ", "-").lower()
        # Remove any path traversal
        clean = os.path.normpath(clean).lstrip("/")
        # Ensure .md extension (don't double-add)
        if not clean.endswith(".md"):
            clean += ".md"
        return self.wiki_dir / clean

    def page_name_from_path(self, file_path: Path) -> str:
        """Convert a filesystem path back to a page name."""
        rel = file_path.relative_to(self.wiki_dir)
        name = str(rel.with_suffix(""))
        return name

    def get_page(self, page_name: str) -> Optional[str]:
        """Get the current markdown content of a page. Returns None if not found."""
        path = self.page_path(page_name)
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def save_page(
        self,
        page_name: str,
        content: str,
        author: str = "ai-agent",
        message: str = "",
    ) -> str:
        """Create or update a page. Returns the commit SHA.
        
        Every save = one Git commit = full version history.
        `author` tracks who made the edit (ai-agent vs human-name).
        """
        path = self.page_path(page_name)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Determine if create or update
        is_new = not path.exists()
        action = "📝" if is_new else "✏️"

        path.write_text(content, encoding="utf-8")

        # Stage and commit
        rel_path = path.relative_to(self.wiki_dir)
        self.repo.index.add([str(rel_path)])

        commit_msg = f"{action} {page_name}"
        if message:
            commit_msg += f"\n\n{message}"

        commit = self.repo.index.commit(
            commit_msg,
            author=git.Actor(author, f"{author}@wiki"),
            committer=git.Actor("Wiki Bot", "wiki@local"),
        )
        return commit.hexsha

    def delete_page(self, page_name: str, author: str = "ai-agent") -> bool:
        """Delete a page. Returns True if deleted, False if not found."""
        path = self.page_path(page_name)
        if not path.exists():
            return False

        rel_path = path.relative_to(self.wiki_dir)
        self.repo.index.remove([str(rel_path)])

        path.unlink()

        commit = self.repo.index.commit(
            f"🗑️ {page_name}",
            author=git.Actor(author, f"{author}@wiki"),
            committer=git.Actor("Wiki Bot", "wiki@local"),
        )
        return True

    # ── version history ────────────────────────────────────────

    def get_history(self, page_name: str, max_count: int = 50) -> list[dict]:
        """Get version history for a page.
        Returns list of {sha, author, date, message, summary}.
        """
        path = self.page_path(page_name)
        if not path.exists():
            # Check if the page existed but was deleted
            pass

        rel_path = str(path.relative_to(self.wiki_dir))

        try:
            commits = list(
                self.repo.iter_commits(paths=rel_path, max_count=max_count)
            )
        except git.NoSuchPathError:
            return []

        history = []
        for c in commits:
            history.append({
                "sha": c.hexsha,
                "short_sha": c.hexsha[:8],
                "author": c.author.name,
                "author_email": c.author.email,
                "date": datetime.fromtimestamp(c.committed_date, tz=timezone.utc).isoformat(),
                "message": c.message.strip(),
                "summary": c.message.split("\n")[0].strip(),
            })
        return history

    def get_version(self, page_name: str, commit_sha: str) -> Optional[str]:
        """Get page content at a specific commit. Returns None if not found."""
        path = self.page_path(page_name)
        rel_path = str(path.relative_to(self.wiki_dir))

        try:
            commit = self.repo.commit(commit_sha)
            blob = commit.tree / rel_path
            return blob.data_stream.read().decode("utf-8")
        except (KeyError, git.BadName, git.NoSuchPathError):
            return None

    def revert_to(self, page_name: str, commit_sha: str, author: str = "ai-agent") -> Optional[str]:
        """Revert a page to a previous version. Returns new commit SHA."""
        old_content = self.get_version(page_name, commit_sha)
        if old_content is None:
            return None
        return self.save_page(
            page_name,
            old_content,
            author=author,
            message=f"⏪ reverted to {commit_sha[:8]}",
        )

    def diff_versions(self, page_name: str, sha_a: str, sha_b: str) -> str:
        """Get diff between two versions of a page."""
        path = self.page_path(page_name)
        rel_path = str(path.relative_to(self.wiki_dir))

        try:
            commit_a = self.repo.commit(sha_a)
            commit_b = self.repo.commit(sha_b)
            diffs = commit_b.diff(commit_a, paths=rel_path, create_patch=True)
            if diffs:
                diff_bytes = diffs[0].diff
                if isinstance(diff_bytes, bytes):
                    return diff_bytes.decode("utf-8", errors="replace")
                return str(diff_bytes)
        except (KeyError, git.BadName):
            pass
        return ""

    # ── listing ────────────────────────────────────────────────

    def list_pages(self) -> list[dict]:
        """List all pages with metadata.
        Returns [{name, path, title, last_modified, word_count}]
        """
        pages = []
        for md_file in sorted(self.wiki_dir.rglob("*.md")):
            # Skip .gitkeep
            if md_file.name == ".gitkeep":
                continue
            rel = md_file.relative_to(self.wiki_dir)
            name = str(rel.with_suffix(""))
            content = md_file.read_text(encoding="utf-8")
            title = self._extract_title(content) or name.split("/")[-1]

            # Get last commit for this file
            last_commit = None
            try:
                commits = list(
                    self.repo.iter_commits(paths=str(rel), max_count=1)
                )
                if commits:
                    last_commit = datetime.fromtimestamp(
                        commits[0].committed_date, tz=timezone.utc
                    ).isoformat()
            except (git.NoSuchPathError, ValueError):
                pass

            pages.append({
                "name": name,
                "path": str(rel),
                "title": title,
                "last_modified": last_commit,
                "word_count": len(content.split()),
            })
        return pages

    def search_pages(self, query: str) -> list[dict]:
        """Full-text search across all pages. Simple substring match."""
        query_lower = query.lower()
        results = []
        for page in self.list_pages():
            content = self.get_page(page["name"])
            if content and query_lower in content.lower():
                results.append({
                    **page,
                    "snippet": self._make_snippet(content, query_lower),
                })
        return results

    # ── helpers ────────────────────────────────────────────────

    def _extract_title(self, content: str) -> Optional[str]:
        """Extract the first # Heading from markdown."""
        match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        if match:
            return match.group(1).strip()
        return None

    def _make_snippet(self, content: str, query: str, context: int = 60) -> str:
        """Extract a snippet around the first match of query."""
        idx = content.lower().find(query)
        if idx == -1:
            return content[:200] + "..."
        start = max(0, idx - context)
        end = min(len(content), idx + len(query) + context)
        snippet = content[start:end]
        if start > 0:
            snippet = "..." + snippet
        if end < len(content):
            snippet = snippet + "..."
        return snippet

    def raw_content(self, file_path: str) -> Optional[str]:
        """Get raw content of any wiki file (non-md assets)."""
        full_path = self.wiki_dir / file_path
        if full_path.exists() and full_path.is_relative_to(self.wiki_dir):
            return full_path.read_bytes()
        return None
