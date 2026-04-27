# Chat Feedback & Scope API

**Last updated:** 2026-04-27  
**Base path:** `/api/v1`

---

## Scope contract (as of Candidate 5)

Scope is now **system + area only**. `document_type_filters` and `preferred_document_types` are accepted for backward compatibility but are silently ignored — no filter predicate or retrieval weighting is applied.

| Scope axis | Status | Notes |
|---|---|---|
| `system` | **Active** | Required for all scoped requests |
| `area` | **Active** | Required for all scoped requests |
| `document_type` | **Deprecated** | Accepted, ignored, no 422 raised |

---

## POST /api/v1/chat/feedback

Submit thumbs up/down feedback for an assistant answer.

**Auth:** Bearer JWT — any authenticated user.

### Request

```http
POST /api/v1/chat/feedback
Content-Type: application/json
Authorization: Bearer <token>
```

```json
{
  "conversation_id": "uuid",
  "message_id": "uuid",
  "rating": "thumbs_up",
  "reason_code": "helpful",
  "comment": "Exact citation matched the SOP."
}
```

| Field | Type | Required | Description |
|---|---|---|---|
| `conversation_id` | UUID | Yes | Conversation the answer belongs to |
| `message_id` | UUID | Yes | Specific assistant message being rated |
| `rating` | `thumbs_up` \| `thumbs_down` | Yes | User rating |
| `reason_code` | string | No | Short classification: `helpful`, `not_relevant`, `wrong_citation`, `hallucinated`, `too_long`, `other` |
| `comment` | string | No | Free-text comment (max 1000 chars) |

### Response — 201 Created

```json
{
  "id": "uuid",
  "conversation_id": "uuid",
  "message_id": "uuid",
  "rating": "thumbs_up",
  "reason_code": "helpful",
  "created_at": "2026-04-27T12:00:00Z"
}
```

### Error responses

| Status | Code | Description |
|---|---|---|
| 400 | `FEEDBACK_INVALID` | Missing required fields or invalid rating value |
| 404 | `CONVERSATION_NOT_FOUND` | `conversation_id` does not belong to caller |
| 409 | `FEEDBACK_DUPLICATE` | Identical payload already submitted (same session; edited payloads are allowed) |

---

## GET /api/v1/chat/feedback/metrics

Retrieve aggregate answer-quality metrics. **Role-gated to `admin`, `reviewer`, `plantig_admin`, `plantig_reviewer`.**

**Auth:** Bearer JWT — admin or reviewer role required.

### Request

```http
GET /api/v1/chat/feedback/metrics?window=7d&system=plantops&area=boiler
Authorization: Bearer <token>
```

| Query parameter | Type | Required | Description |
|---|---|---|---|
| `window` | `1d` \| `7d` \| `30d` | No | Lookback window. Default: `7d` |
| `system` | string | No | Filter to a specific system scope |
| `area` | string | No | Filter to a specific area scope |

### Response — 200 OK

```json
{
  "window": "7d",
  "total_feedback": 142,
  "thumbs_up": 118,
  "thumbs_down": 24,
  "positive_rate": 0.831,
  "flagged_answers": 3,
  "top_negative_reason_codes": [
    { "reason_code": "wrong_citation", "count": 11 },
    { "reason_code": "not_relevant", "count": 8 }
  ],
  "snapshot_at": "2026-04-27T12:00:00Z"
}
```

### Error responses

| Status | Code | Description |
|---|---|---|
| 403 | `FORBIDDEN` | Caller does not have admin or reviewer role |

---

## Scope governance enforcement (Candidates 1 & 5)

All write operations (upload, chat query) enforce the caller's `user_scope_policies` row.  
Requests that fall outside the assigned system/area policy are rejected with:

```http
HTTP/1.1 403 Forbidden
Content-Type: application/json
```

```json
{
  "detail": {
    "code": "SCOPE_ACCESS_DENIED",
    "reason_code": "OUTSIDE_POLICY",
    "message": "Access denied: requested scope is outside your assigned policy.",
    "requested_scope": { "system": "plantops", "area": "turbine" }
  }
}
```

The denial is written to `access_audit_logs` before the response is returned.

Frontend behaviour on `SCOPE_ACCESS_DENIED`:
- Chat: inline denial banner; retry input locked until scope is changed.
- Upload: form submission blocked; actionable message shown.
