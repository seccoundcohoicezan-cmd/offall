"""Writes docs/API.md from the live OpenAPI schema: python scripts/export_api_md.py"""

import os
import sys
from pathlib import Path

os.environ.setdefault("MASTER_ENCRYPTION_KEY", "ZGV2LW9ubHktbWFzdGVyLWtleS1jaGFuZ2UtbWUhISE=")
os.environ.setdefault("JWT_SECRET", "docs")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.main import create_app  # noqa: E402

PUBLIC = {
    "/api/v1/auth/register",
    "/api/v1/auth/login",
    "/api/v1/auth/refresh",
    "/api/v1/auth/logout",
    "/health",
    "/api/v1/health",
}


def main() -> None:
    spec = create_app(redis=object(), queue=object()).openapi()
    lines = [
        "# API",
        "",
        "Generated from the FastAPI OpenAPI schema (`backend/scripts/export_api_md.py`).",
        "Interactive docs: `/docs` on the API service (internal; not proxied by the frontend).",
        "",
        "- Base path `/api/v1`. Auth: `Authorization: Bearer <access>` **or** the httpOnly cookie",
        "  `offall_access` set by login/register. Access token 15 min, refresh 7 days (rotated, revocable).",
        '- Errors are always `{"error": {"code": "...", "message": "..."}}`.',
        "- Lists are paginated with `limit` / `offset` and return `{items, total, limit, offset}`.",
        "",
        "| Method | Path | Auth | Summary |",
        "|---|---|---|---|",
    ]
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            auth = "-" if path in PUBLIC else "yes"
            summary = (op.get("description") or op.get("summary") or "").strip().splitlines()[0]
            lines.append(f"| {method.upper()} | `{path}` | {auth} | {summary} |")
    lines += [
        "",
        "## Job streaming (SSE)",
        "",
        "`GET /api/v1/jobs/{id}/stream` returns `text/event-stream`. Events:",
        "",
        "| event | data |",
        "|---|---|",
        "| `status` | `{status, detail?, retry_at?}` (running, rotating, waiting_quota) |",
        "| `delta` | `{text}` - append to the answer |",
        "| `snapshot` | `{text, status}` - replace the answer (sent when the Redis stream expired) |",
        "| `done` | `{status, message_id, model_used, tokens_saved, cached}` |",
        "| `error` | `{status: failed, error}` |",
        "",
        "Every event from the Redis stream carries an `id:`. Reconnect with header `Last-Event-ID`",
        "(or `?last_event_id=`) to resume without gaps; without it the whole answer is replayed.",
        "",
    ]
    out = Path(__file__).resolve().parents[2] / "docs" / "API.md"
    out.write_text("\n".join(lines))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
