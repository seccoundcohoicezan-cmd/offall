# API

Generated from the FastAPI OpenAPI schema (`backend/scripts/export_api_md.py`).
Interactive docs: `/docs` on the API service (internal; not proxied by the frontend).

- Base path `/api/v1`. Auth: `Authorization: Bearer <access>` **or** the httpOnly cookie
  `offall_access` set by login/register. Access token 15 min, refresh 7 days (rotated, revocable).
- Errors are always `{"error": {"code": "...", "message": "..."}}`.
- Lists are paginated with `limit` / `offset` and return `{items, total, limit, offset}`.

| Method | Path | Auth | Summary |
|---|---|---|---|
| POST | `/api/v1/auth/register` | - | Register |
| POST | `/api/v1/auth/login` | - | Login |
| POST | `/api/v1/auth/refresh` | - | Refresh |
| POST | `/api/v1/auth/logout` | - | Logout |
| GET | `/api/v1/auth/config` | yes | Public: lets the login/register pages know whether self sign-up is open. |
| GET | `/api/v1/auth/me` | yes | Me |
| GET | `/api/v1/providers` | yes | List Providers |
| POST | `/api/v1/providers` | yes | Create Provider |
| PATCH | `/api/v1/providers/{provider_id}` | yes | Patch Provider |
| DELETE | `/api/v1/providers/{provider_id}` | yes | Delete Provider |
| POST | `/api/v1/providers/{provider_id}/keys` | yes | Add Key |
| PATCH | `/api/v1/providers/{provider_id}/keys/{key_id}` | yes | Patch Key |
| DELETE | `/api/v1/providers/{provider_id}/keys/{key_id}` | yes | Delete Key |
| POST | `/api/v1/providers/{provider_id}/keys/{key_id}/test` | yes | Test Key |
| GET | `/api/v1/models` | yes | Models whose provider has at least one active key (all models with include_all=true). |
| PATCH | `/api/v1/models/{provider_id}/{model_name}` | yes | Toggle Model |
| GET | `/api/v1/agents` | yes | List Agents |
| POST | `/api/v1/agents` | yes | Create Agent |
| PATCH | `/api/v1/agents/{agent_id}` | yes | Patch Agent |
| DELETE | `/api/v1/agents/{agent_id}` | yes | Delete Agent |
| GET | `/api/v1/chats` | yes | List Chats |
| POST | `/api/v1/chats` | yes | Create Chat |
| GET | `/api/v1/chats/{chat_id}` | yes | Get Chat |
| PATCH | `/api/v1/chats/{chat_id}` | yes | Patch Chat |
| DELETE | `/api/v1/chats/{chat_id}` | yes | Delete Chat |
| GET | `/api/v1/chats/{chat_id}/messages` | yes | List Messages |
| POST | `/api/v1/chats/{chat_id}/messages` | yes | Stores the prompt, creates a job and returns at once; the worker does the AI call. |
| GET | `/api/v1/jobs` | yes | List Jobs |
| GET | `/api/v1/jobs/{job_id}` | yes | Get Job |
| POST | `/api/v1/jobs/{job_id}/cancel` | yes | Cancel Job |
| POST | `/api/v1/jobs/{job_id}/retry` | yes | Re-run a failed/cancelled job for the same user message (no duplicate prompt). |
| GET | `/api/v1/jobs/{job_id}/stream` | yes | Stream Job |
| GET | `/api/v1/usage/summary` | yes | Usage Summary |
| GET | `/api/v1/settings` | yes | Get User Settings |
| PATCH | `/api/v1/settings` | yes | Patch User Settings |
| POST | `/api/v1/push/subscribe` | yes | Push Subscribe |
| GET | `/api/v1/admin/users` | yes | List Users |
| POST | `/api/v1/admin/users` | yes | Create User |
| PATCH | `/api/v1/admin/users/{user_id}` | yes | Patch User |
| DELETE | `/api/v1/admin/users/{user_id}` | yes | Delete User |
| GET | `/api/v1/admin/settings` | yes | Get Instance Settings |
| PATCH | `/api/v1/admin/settings` | yes | Patch Instance Settings |
| GET | `/health` | - | Health |
| GET | `/api/v1/health` | - | Health |

## Job streaming (SSE)

`GET /api/v1/jobs/{id}/stream` returns `text/event-stream`. Events:

| event | data |
|---|---|
| `status` | `{status, detail?, retry_at?}` (running, rotating, waiting_quota) |
| `delta` | `{text}` - append to the answer |
| `snapshot` | `{text, status}` - replace the answer (sent when the Redis stream expired) |
| `done` | `{status, message_id, model_used, tokens_saved, cached}` |
| `error` | `{status: failed, error}` |

Every event from the Redis stream carries an `id:`. Reconnect with header `Last-Event-ID`
(or `?last_event_id=`) to resume without gaps; without it the whole answer is replayed.
