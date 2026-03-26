# Settings API — Frontend Contract

**Endpoints:** `GET /api/v1/settings`, `PUT /api/v1/settings`  
**Persistence:** General settings are now stored in the backend. Changes persist across sessions.  
**Note:** Scheduling settings use a separate API. See [SCHEDULING_SETTINGS_FRONTEND.md](./SCHEDULING_SETTINGS_FRONTEND.md).

---

## GET /api/v1/settings

**Response (200)** `data`:

| Field | Type | Notes |
|-------|------|-------|
| `theme` | `string` | e.g. `"light"`, `"dark"` |
| `language` | `string` | e.g. `"en"`, `"zh"` |
| `notifications` | `boolean` | Global notifications on/off |
| `ai_enabled` | `boolean` | AI features on/off |
| `integrations` | `string[]` | e.g. `["erp", "mes"]` — read-only |

**Example:**
```json
{
  "success": true,
  "data": {
    "theme": "light",
    "language": "en",
    "notifications": true,
    "ai_enabled": true,
    "integrations": ["erp", "mes"]
  }
}
```

---

## PUT /api/v1/settings

**Request body:** All fields optional. Only include fields you are updating.

| Field | Type | Notes |
|-------|------|-------|
| `theme` | `string` | optional |
| `language` | `string` | optional |
| `notifications` | `boolean` | optional — **prefer boolean** |
| `ai_enabled` | `boolean` | optional — **prefer boolean** |

### Fields NOT accepted by PUT /settings

Do **not** include these in the PUT payload. The backend will ignore them, but sending incompatible types can cause errors:

| Field | Why not sent |
|-------|--------------|
| `timezone` | Not in API contract |
| `simulation_mode` | Not in API contract |
| `auto_save_interval` | Not in API contract |
| `data_retention_days` | Not in API contract |
| `erp_integration` | Not in API contract (object) |
| `integrations` | Read-only; not accepted on update |

### Recommended PUT payload (minimal)

```json
{
  "theme": "dark",
  "language": "zh",
  "notifications": true,
  "ai_enabled": false
}
```

### Backend tolerance

The backend accepts `notifications` and `ai_enabled` as either:

- **Boolean:** `"notifications": true` ✅ (preferred)
- **Object with `enabled`:** `"notifications": { "enabled": true }` ✅ (legacy tolerance)

For new code, send booleans only.

---

## Response (200)

Same structure as GET /settings:

```json
{
  "success": true,
  "data": {
    "theme": "dark",
    "language": "zh",
    "notifications": true,
    "ai_enabled": false,
    "integrations": ["erp", "mes"]
  }
}
```

---

## Error handling

- **400 Bad Request** — Invalid JSON or type mismatch (e.g. `theme` as number).
  - `{"success": false, "error": "json: cannot unmarshal ..."}`

If you receive `cannot unmarshal object into Go struct field ... of type bool`, ensure `notifications` and `ai_enabled` are booleans or `{ "enabled": true/false }`, not other object shapes.

---

## If save still fails — frontend checklist

1. **Payload** — Send only `theme`, `language`, `notifications`, `ai_enabled` in the PUT body. Omit all other fields (`timezone`, `simulation_mode`, `erp_integration`, etc.).
2. **After successful save** — Update your local UI state from the PUT response `data`, or call `GET /api/v1/settings` to refresh. The backend now persists values.
3. **Boolean fields** — Prefer `"notifications": true` (not `{"enabled": true}`). Both work, but booleans are preferred.

---

## Scheduling settings (separate API)

Scheduling-related fields (lock-in window, split strategy, work times, etc.) are managed via:

- `GET /api/v1/scheduling/settings`
- `PUT /api/v1/scheduling/settings`

See [SCHEDULING_SETTINGS_FRONTEND.md](./SCHEDULING_SETTINGS_FRONTEND.md).
