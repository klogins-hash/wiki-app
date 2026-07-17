# Version History

Every edit to every page is automatically **versioned using Git**. This gives you full audit trail, diff capability, and revert.

## What Gets Tracked

| Field | Description |
|---|---|
| **Commit SHA** | Unique identifier for every change |
| **Author** | Who made the edit (`ai-agent` or human name) |
| **Timestamp** | When the change was made |
| **Message** | Description of what changed |

## API Endpoints

- `GET /api/pages/{path}/history` — Full version history
- `GET /api/pages/{path}/version/{sha}` — Content at a specific version
- `GET /api/pages/{path}/diff?from={sha}&to={sha}` — Diff between versions
- `POST /api/pages/{path}/revert/{sha}` — Revert to a previous version

## AI Agent Attribution

Every API call includes an `author` field. By default, AI agent edits are attributed to `ai-agent`. You can set custom author names:

```json
PUT /api/pages/my-page
{
  "content": "# New Content",
  "author": "claude-agent",
  "message": "Updated docs with new findings"
}
```

This makes it easy to track which agent or human made each change.