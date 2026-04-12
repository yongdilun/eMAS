# Frontend scheduling expectations (for backend review)

This document describes what the **eMas web app** assumes about scheduling and shortage APIs so backend implementations can be checked for alignment. It complements `docs/SHORTAGE_PLANNING_API_FRONTEND_GUIDE.md`, `docs/SHORTAGE_RESOLUTION_UI_BACKEND_ADDENDUM.md`, and `SCHEDULING_API_REFERENCE.md`.

**Base URL (dev):** `http://localhost:8080/api/v1`  
**Planner writes:** requests use header `X-User-Role: planner` where required.

---

## 1. Response envelope and `message`

**Backend (actual):** `dto.Response` exposes **`success`**, **`data`**, **`error`** — there is **no top-level `message`** field on the envelope. Partial-batch / late-job text is carried **inside `data`**, e.g. **`data.message`**, **`data.partial`**, alongside **`data.proposals`** and **`data.summary`** (see batch handlers).

The UI still **merges** `data.message` with any legacy or alternate top-level fields when normalizing (`unwrapSchedulingBatchPayload` in `src/services/api.js`) so nothing is dropped if the shape varies.

**Expectations**

- Partial batch / timeout with some proposals: **HTTP 200** with **`data.message`** set, **`data.proposals`** and **`data.summary`** populated consistently (including generated / blocked / skipped / late via batch summary types).
- **Late jobs:** when `late_count > 0`, **`data.message`** may include a late-jobs line (e.g. `buildLateJobsMessage`).

**Backend check:** integration tests can assert **`data.message`** (and optional **`data.partial`**) on partial-batch responses; outer envelope does not need a duplicate `message` unless you add it later for symmetry.

---

## 2. Batch scheduling endpoints

| Endpoint | Method | Role | Frontend use |
|----------|--------|------|--------------|
| `/ai/scheduling/batch-proposals` | POST | planner | Generate draft proposals (e.g. scope `all_unscheduled`) |
| `/ai/scheduling/reschedule-all` | POST | planner | Cancel/regenerate full draft set (global reschedule) |

**Expectations**

- Response body includes **`proposals`** (array) and, when applicable, **`summary`** (e.g. generated, late, skipped, blocked counts).
- Long-running work: the browser uses an extended client timeout (configurable via `VITE_SCHEDULING_LONG_TIMEOUT_MS` at build time; default is long). If the user still sees **“Request timed out or cancelled; partial results returned”** inside **`data.message`**, that usually indicates **server-side or proxy** limits, not the browser aborting first.
- **Backend / proxy:** ensure HTTP and reverse-proxy timeouts for these routes are high enough for the largest expected job set (often 90s+ or more for many jobs).

---

## 3. `apply-replenishment` vs `option_type`

**Endpoint:** `POST /ai/scheduling/proposals/{proposal_id}/apply-replenishment`

**Backend (actual):** Request body is **`suggestions[]`** with material fields (material id, quantity, arrive_at, optional inventory snapshot). **There is no `option_type` in the DTO.** The handler creates expected arrivals from those rows; it does **not** validate planner “resolution kind” in the body.

**Frontend expectation**

- The UI builds **`suggestions`** only for recommendations whose **`option_type`** (from shortage analysis / proposal payloads) is treated as **material replenishment** (e.g. `replenish`, synonyms). Rows with **`schedule_production`** (or other non-replenish actions) are **not** sent — **this is client-side filtering**, not something the server rejects with 4xx for “wrong option_type”.
- If proposals only expose **`schedule_production`** resolutions for the selected jobs, **Apply selected + Reschedule all** has **nothing to apply** via this endpoint; the UI offers **Reschedule all (no material apply)** instead.

**Backend product note:** Shortage resolution options include **`option_type`** values such as **`replenish`**, **`schedule_production`**, **`delay_jobs`**, etc. If the solver **only** returns **`schedule_production`** for a scenario where material arrivals would help, planners will not see a replenish path in the UI — that is a **resolution mix / solver output** concern, not a broken route.

**Path note:** URL may include **`proposal_id`**; if the backend does not yet bind or validate suggestions against that id, traceability is a possible future extension.

---

## 4. Recommendation shape (shortage / proposals)

The UI normalizes recommendations from:

- `proposal.shortage_resolutions`, or  
- `proposal.material_shortages[].per_material_resolutions` when the primary list is empty.

**Expectations**

- **`option_type`** should be stable and lowercase-friendly (`replenish`, `schedule_production`, etc.). The client normalizes casing for display and logic.
- **Material identity:** `material_id` (or fields the normalizer maps to `entity_id`) should be consistent so `apply-replenishment` receives a valid `material_id`.
- **Quantities and times:** `suggested_qty` and `suggested_arrive_at` (or nested `replenishment.*`) should be present for replenish rows when the backend intends them to be applicable.

---

## 5. Shortage Resolution Center (embedded modal)

**Flow**

1. User selects recommendation rows (checkboxes).
2. **Apply selected + Reschedule all:** runs `apply-replenishment` per proposal for **replenish**-eligible suggestions, then **`reschedule-all`**.
3. **Reschedule all (no material apply):** runs **`reschedule-all`** only (used when selections are not material replenishment, e.g. only `schedule_production`).

**Backend expectation**

- After **`reschedule-all`**, returned **`proposals`** should reflect regenerated drafts if the server has applied inventory / arrival state from prior **`apply-replenishment`** calls in the same session.
- **Backend evidence:** expected arrivals are persisted; planning / readiness paths use **ListExpectedArrivals** so **`reschedule-all`** can see new arrivals after they are committed.

---

## 6. “Apply selected + Reschedule all” looked unusable — backend or frontend?

**Conclusion from frontend runtime logs (Shortage Resolution):**

| Cause | Verdict |
|--------|--------|
| Missing batch routes or wrong role | **Not supported by evidence** — batch-proposals / reschedule-all exist with appropriate roles. |
| Backend dropping `message` on envelope | **N/A** — backend uses **`data.message`**; UI reads merged `data` fields. |
| `apply-replenishment` rejecting `schedule_production` in body | **N/A** — body has no `option_type`; server does not classify by that field. |
| **Selections were only `schedule_production`** | **Confirmed** — logs showed **`isReplenish: false`** for all selected rows; **no** `suggestions` were built for apply-replenishment. |
| UX: button disabled / error toast | **Frontend** — addressed by enabling when selections exist, info copy, and **Reschedule all (no material apply)**. |

So the **issue was not** “backend batch failed.” It was **mismatch between** what the UI bulk action does (**apply material arrivals + reschedule**) **and** the **resolution types returned** for those proposals (**only** `schedule_production` in the observed case). Improving outcomes may require **solver / shortage analysis** to also emit **`replenish`** options when appropriate; that is **product/backend logic**, not a frontend transport bug.

---

## 7. Verify-overlaps and replenish-and-replan

- **`verify-overlaps`** and **`replenish-and-replan`** use the same long-timeout pattern as other heavy POSTs where configured in the client.
- **`replenish-and-replan`** is per-job; the bulk Shortage page prefers global **`apply-replenishment`** + **`reschedule-all`** for multi-proposal edits.

---

## 8. Error and conflict semantics

- **409** (e.g. **`snapshot_conflict`** on apply-replenishment): inventory changed since analysis; UI shows refresh/retry style messages.
- **4xx** bodies: responses use **`error`** (string) in the common wrapper; the client’s `parseErrorBody` also picks up **`detail`** / **`message`** when present. Toasts use the parsed string — no strict requirement for a separate **`detail`** key only.

---

## 9. Checklist for backend QA

| Topic | Verify |
|--------|--------|
| Envelope | **`data.message`** / **`data.partial`** on partial batch; **`data.proposals`** + **`data.summary`** consistent |
| Timeouts | Server and proxy timeouts ≥ worst-case batch; partial results in **`data.message`** |
| Shortage mix | When material arrivals are intended, **replenish**-style `option_type` appears in resolutions where applicable |
| Reschedule after arrivals | Expected arrivals committed; **`reschedule-all`** planning sees them (see ListExpectedArrivals / material availability paths) |
| Summary | `summary` fields (generated / blocked / skipped / late) align with returned `proposals` |

---

## References

- `docs/SHORTAGE_PLANNING_API_FRONTEND_GUIDE.md` — endpoint payloads and shortage fields  
- `docs/SHORTAGE_RESOLUTION_UI_BACKEND_ADDENDUM.md` — optional bundle/validate APIs  
- `docs/SCHEDULING_BACKEND_OPTIONS.md` — timeout / partial-result notes  
- `src/services/api.js` — `unwrapSchedulingBatchPayload`, `SCHEDULING_LONG_TIMEOUT_MS`  
- `src/services/normalizers.js` — `normalizeRecommendation`, `isReplenishRecommendation`
