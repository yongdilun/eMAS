# AI Chat API Specification

This document defines the backend API required for the AI chat feature. The frontend calls these endpoints to create, list, load, and send messages in persisted conversations.

**Base path:** `/api/v1/ai/chats`

**Authentication:** Use the same auth as existing `/api/v1/ai/command` (session, JWT, or API key as applicable). Conversations are **not per-user** – they are shared for the deployment (single-tenant). Do not send `X-User-Id` for chat endpoints.

---

## 1. GET /api/v1/ai/chats

List conversations, ordered by most recently updated first.

**Request:** No body. Optional query params for pagination (e.g. `limit`, `offset`) if needed.

**Response (200)** `data`:

```json
{
  "data": [
    {
      "id": "chat-uuid-1",
      "title": "Line 3 OEE Analysis",
      "created_at": "2026-03-09T10:20:00Z",
      "updated_at": "2026-03-09T10:22:00Z"
    }
  ]
}
```

| Field        | Type     | Description                                |
|-------------|----------|--------------------------------------------|
| `id`        | `string` | Unique conversation ID                     |
| `title`     | `string` | Display title (e.g. first user message or auto-generated) |
| `created_at`| `string` | RFC3339 timestamp                          |
| `updated_at`| `string` | RFC3339 timestamp of last activity         |

**Errors:**
- `404` – Endpoint not implemented (frontend shows empty list)
- `401` – Unauthorized

---

## 2. POST /api/v1/ai/chats

Create a new conversation.

**Request body (optional):**

```json
{}
```

Or with optional initial metadata:

```json
{
  "title": "Custom title"
}
```

**Response (201)** `data`:

```json
{
  "data": {
    "id": "chat-uuid-new",
    "title": "New conversation",
    "created_at": "2026-03-09T10:25:00Z",
    "updated_at": "2026-03-09T10:25:00Z"
  }
}
```

| Field        | Type     | Description        |
|-------------|----------|--------------------|
| `id`        | `string` | New conversation ID|
| `title`     | `string` | Display title      |
| `created_at`| `string` | RFC3339            |
| `updated_at`| `string` | RFC3339            |

---

## 3. GET /api/v1/ai/chats/:id

Get a single conversation with its full message history.

**Path parameters:**
| Name | Type     | Description      |
|------|----------|------------------|
| `id` | `string` | Conversation ID  |

**Response (200)** `data`:

```json
{
  "data": {
    "id": "chat-uuid-1",
    "title": "Line 3 OEE Analysis",
    "created_at": "2026-03-09T10:20:00Z",
    "updated_at": "2026-03-09T10:22:00Z",
    "messages": [
      {
        "id": "msg-1",
        "role": "assistant",
        "content": "Welcome back! How can I assist you with smart factory operations today?",
        "timestamp": "2026-03-09T10:20:00Z"
      },
      {
        "id": "msg-2",
        "role": "user",
        "content": "What is the current OEE for Line 3?",
        "timestamp": "2026-03-09T10:21:00Z"
      },
      {
        "id": "msg-3",
        "role": "assistant",
        "content": "The current OEE for Line 3 is 85%.",
        "timestamp": "2026-03-09T10:22:00Z",
        "intent": "job_status",
        "result_cards": [...]
      }
    ]
  }
}
```

**Message object:**

| Field           | Type     | Description                                      |
|----------------|----------|--------------------------------------------------|
| `id`           | `string` | Unique message ID                                |
| `role`         | `string` | `"user"` or `"assistant"`                        |
| `content`      | `string` | Message text                                     |
| `timestamp`    | `string` | RFC3339 (optional)                               |
| `intent`       | `string` | Parsed intent (for assistant messages)           |
| `result_cards` | `array`  | Structured cards (see POST /api/v1/ai/command)  |
| `assist`       | `object` | Scheduling assist payload (optional)             |
| `proposal`     | `object` | Scheduling proposal (optional)                   |

**Errors:**
- `404` – Conversation not found
- `401` – Unauthorized

---

## 4. POST /api/v1/ai/chats/:id/messages

Send a user message, call the AI, persist both user and assistant messages, and return the assistant response.

**Path parameters:**
| Name | Type     | Description      |
|------|----------|------------------|
| `id` | `string` | Conversation ID  |

**Request body:**

```json
{
  "query": "What is the current OEE for Line 3?"
}
```

| Field   | Type     | Required | Description        |
|---------|----------|----------|--------------------|
| `query` | `string` | Yes      | User's message     |

**Implementation note:** The backend should:
1. Persist the user message to the conversation
2. Call the existing `POST /api/v1/ai/command` logic internally with `execute_readonly: true`
3. Persist the assistant response to the conversation
4. Return the assistant response in the format below

**Response (200)** `data`:

```json
{
  "data": {
    "message": "The current OEE for Line 3 is 85%.",
    "intent": "job_status",
    "confidence": 0.95,
    "ambiguous": false,
    "clarifications": [],
    "result_cards": [
      {
        "kind": "job_status",
        "title": "Line 3 OEE",
        "tone": "positive",
        "summary": "OEE at 85%",
        "metrics": [{"label": "OEE", "value": "85%"}]
      }
    ],
    "entities": {"job_id": "JOB-001"},
    "suggested_calls": []
  }
}
```

The response shape should match the existing `POST /api/v1/ai/command` response (see API.md) so the frontend can render result cards, intents, clarifications, and trigger scheduling assist when `intent` is `reschedule` or `propose_schedule`.

| Field            | Type     | Description                                    |
|------------------|----------|------------------------------------------------|
| `message`        | `string` | Human-readable assistant reply                 |
| `intent`         | `string` | Parsed intent                                  |
| `confidence`     | `number` | 0–1                                            |
| `ambiguous`      | `boolean`| Needs clarification                            |
| `clarifications` | `array`  | Follow-up prompts                              |
| `result_cards`   | `array`  | UI cards (see API.md)                          |
| `entities`       | `object` | Extracted entities (e.g. job_id)               |
| `suggested_calls`| `array`  | Suggested API calls                            |

**Errors:**
- `404` – Conversation not found
- `400` – Invalid request (e.g. empty query)
- `401` – Unauthorized
- `500` – AI/command service error

---

## Summary Table

| Endpoint                        | Method | Purpose                              |
|---------------------------------|--------|--------------------------------------|
| `/api/v1/ai/chats`              | GET    | List conversations (most recent first) |
| `/api/v1/ai/chats`              | POST   | Create new conversation              |
| `/api/v1/ai/chats/:id`          | GET    | Get conversation with messages       |
| `/api/v1/ai/chats/:id/messages` | POST   | Send message, get AI response, persist |

---

## Data Model (Suggested)

**conversations** table:
- `id` (PK)
- `title`
- `created_at`
- `updated_at`

**messages** table:
- `id` (PK)
- `conversation_id` (FK)
- `role` (`user` | `assistant`)
- `content` (text)
- `metadata` (JSONB for intent, result_cards, etc.)
- `created_at`

---

## Frontend Integration Notes

**No user model:** Do not rely on `user_id` or "current user" semantics. All chat conversations are shared for the deployment (single-tenant). You do not need to send `X-User-Id` for chat endpoints. The `X-User-Role` header may still be required for scheduling write operations (approve/reject/apply) if those are triggered from chat flows.

**Implementation status:** The chat endpoints are **implemented** and available at `GET/POST /api/v1/ai/chats`, `GET /api/v1/ai/chats/:id`, and `POST /api/v1/ai/chats/:id/messages`. For stateless queries without conversation persistence, use `POST /api/v1/ai/command` with `{"query": "...", "execute_readonly": true}`.
