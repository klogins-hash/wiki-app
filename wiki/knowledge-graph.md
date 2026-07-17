# Knowledge Graph

The AI Wiki uses `[[wikilinks]]` to build a **directed knowledge graph** of all pages and their relationships.

## How It Works

When you write `[[Page Name]]` in any page's markdown, the system:

1. Registers a **link** from the current page to `Page Name`
2. When `Page Name` exists, it shows up as a clickable link with a purple underline
3. When `Page Name` doesn't exist yet, it's tracked as a **broken link** — the graph still shows it as a planned node

## Graph Features

- **Full graph**: `GET /api/graph` returns all nodes and edges as JSON
- **Local graph**: `GET /api/graph/local/{page}` returns the subgraph around a page
- **Backlinks**: `GET /api/backlinks/{page}` shows which pages link to a given page
- **Visual graph**: Every page shows a D3 force-directed graph of its local connections

## Benefits

- Discover unexpected connections between topics
- Find [[orphaned pages]] that need linking
- Track which pages are most referenced
- Let AI agents automatically link related content