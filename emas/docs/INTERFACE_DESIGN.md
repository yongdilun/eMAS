# eMas Interface Design

Design documentation for every interface in the eMas application: modals, forms, sidebars, panels, and small windows.

**Related:** `SCHEDULING_GAPS_API_CHANGELOG.md`, `AI_CHAT_API_SPEC.md`

---

## 1. Modals

### 1.1 Base Modal (`shared/Modal.jsx`)

Reusable modal shell used by most dialogs.

| Prop | Type | Description |
|------|------|-------------|
| `isOpen` | boolean | Controls visibility |
| `onClose` | function | Called on backdrop click or close button |
| `title` | string | Modal title |
| `children` | node | Content area |
| `size` | `'default' \| 'fullscreen'` | Default: max-w-2xl; fullscreen: inset-4 to inset-8 |

**Layout:** Title bar with close button; scrollable content; backdrop (`bg-black/50`); `z-50`.  
**UX:** Backdrop click closes; dark mode support.

---

### 1.2 Record Downtime Modal

**Purpose:** Record machine downtime (breakdown, maintenance).  
**Component:** `RecordDowntimeModal.jsx`  
**Triggered from:** Machine Resources table; JobDetailsPanel.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| Cause | text | Yes | Reason for downtime |
| Down until | datetime-local | No | Default 2h from now |

**Layout:** Header with machine name; form; Cancel / Record Downtime.  
**UX:** Primary action disabled until cause entered; toast on success; backdrop dismiss.

---

### 1.3 Report Delay Modal

**Purpose:** Report delay for a job (scheduling).  
**Component:** `ReportDelayModal.jsx`  
**Triggered from:** JobDetailsPanel.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| Reason | text | No | Delay reason |
| Delay | number | No | Minutes (default 60) |

**Layout:** Compact form; Cancel / Report Delay.  
**UX:** Success auto-close ~1.5s; toast about rescheduling.

---

### 1.4 Urgent Insert Modal

**Purpose:** Emit urgent insert event for a job.  
**Component:** `UrgentInsertModal.jsx`  
**Triggered from:** JobDetailsPanel; Schedule Preview sidebar.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| Reason | text | No | Urgency reason |
| Priority | select | No | High / Critical |

**Layout:** Same pattern as Report Delay.  
**UX:** Success auto-close; toast.

---

### 1.5 Edit Job Modal

**Purpose:** Edit job priority, deadline, notes.  
**Component:** `EditJobModal.jsx`  
**Triggered from:** JobDetailsPanel.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| Priority | select | No | Job priority |
| Deadline | datetime-local | No | Due date/time |
| Notes | textarea | No | Free-form notes |

**Layout:** Standard form; Cancel / Save.  
**UX:** Pre-filled from selected job.

---

### 1.6 Log Production Modal

**Purpose:** UC-PL01/PL02 — Log production and quality inspection.  
**Component:** `LogProductionModal.jsx`  
**Triggered from:** JobDetailsPanel.

| Tab | Fields |
|-----|--------|
| **Production Log** | Slot selector; Qty Produced; Qty Scrap; Downtime (mins); Notes |
| **Quality Inspection** | Result (pass/fail/conditional radio); Defect Count; Notes |

**Layout:** Tabs; slot dropdown (shows machine + quantity); tab-specific fields; primary submit per tab.  
**UX:** Visual radio for pass/fail/conditional.

---

### 1.7 Add Machine Modal

**Purpose:** Add or edit machine and capabilities.  
**Component:** `AddMachineModal.jsx`  
**Triggered from:** Machine Resources page.

| Field | Type | Description |
|-------|------|-------------|
| Machine ID | text | Read-only in edit mode |
| Machine Name | text | |
| Type | RefSelect | Machine type |
| Status | select | |
| Max Capacity | number | |
| Maintenance Interval | number | |
| Last Maintenance Date | date | |
| Location | RefSelect | |
| Capabilities | repeatable | Step type + efficiency factor; add/remove rows |

**Layout:** 2-column grid on sm+; capabilities as repeatable list; sticky footer Cancel / Save.  
**UX:** RefSelect for type/location; Machine ID disabled when editing.

---

### 1.8 Add Expected Arrival Modal

**Purpose:** Schedule expected material arrivals.  
**Component:** `AddExpectedArrivalModal.jsx`  
**Triggered from:** Storage & Inventory (Expected Arrivals tab).

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| Material | select | Yes | From inventory |
| Quantity | number | Yes | |
| Expected arrival | datetime-local | Yes | |
| Notes | text | No | |

**Layout:** Vertical form; Cancel / Schedule.  
**UX:** Validation for quantity and date.

---

### 1.9 Create Job Modal

**Purpose:** Schedule a new production job.  
**Component:** `CreateJobModal.jsx`  
**Triggered from:** Jobs page.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| Product | RefSelect / manual | Yes | Product ID or Name |
| Assigned Machine | select | No | |
| Start Date | date | No | |
| Start Time | time | No | |
| Duration | number | No | Hours |
| Quantity | number | No | |
| Priority | select | No | |
| Deadline | datetime-local | No | |
| Notes | textarea | No | |

**Layout:** Sticky header; form; sticky footer Cancel / Create Job.  
**UX:** Product select fills productId/productName; optional fallback inputs; per-field validation.

---

### 1.10 Product Modal

**Purpose:** Create or edit product.  
**Location:** Products page.

| Field | Type | Description |
|-------|------|-------------|
| Product ID | text | Read-only in edit |
| Product Name | text | |
| Product Type | RefSelect | |
| Unit of Measure | text | |
| Description | textarea | |

**Layout:** 2-column grid; full-width Name; footer Cancel / Save.  
**UX:** Edit vs create mode.

---

### 1.11 BOM Modal (Process & Formula)

**Purpose:** Manage BOM and process routing for a product. UC-P01.  
**Location:** Products page (BOM action).

| Tab | Content |
|-----|---------|
| **Process** | Process name; steps (step name, machine type) with drag-and-drop; add/remove |
| **Formula** | Formula name; ingredients (material/product, quantity, unit); type toggle; expandable sub-product ingredients |

**Layout:** Tabbed; draggable steps with handles; Formula ingredients with material/product selector.  
**UX:** Drag handles; step name fills machine type from template; save buttons per section.

---

### 1.12 Add Item Modal

**Purpose:** Add or edit inventory item.  
**Component:** `AddItemModal.jsx`  
**Triggered from:** Storage & Inventory.

| Field | Type | Description |
|-------|------|-------------|
| Material Name | text | |
| Material ID | text | Read-only in edit |
| Unit | text | |
| Current Stock | number | |
| Min Stock | number | |
| Storage Location | RefSelect | |

**Layout:** 2-column grid; footer Cancel / Save.  
**UX:** Same add/edit pattern as other modals.

---

### 1.13 Consume Modal

**Purpose:** Consume or receive material. UC-S01.  
**Location:** Storage & Inventory (per-row action).

| Field | Type | Description |
|-------|------|-------------|
| Quantity | number | Required |
| Job ID | text | Consume only; optional |

**Layout:** Item name in header; Cancel / Consume or Receive.  
**UX:** Mode-based title and colors; success auto-close.

---

### 1.14 AI Assistant Modal

**Purpose:** AI chat assistant for factory operations.  
**Component:** `AIAssistantModal.jsx` embeds `AiChatPanel.jsx`.

| Feature | Description |
|---------|-------------|
| Window | Floating, draggable, resizable (min 400×300) |
| Controls | Header drag; resize handles on edges/corners |
| Content | AiChatPanel (messages, input, intent/confidence) |

**Layout:** Non-modal backdrop (pointer-events-none); `aria-modal`, `aria-label`.  
**UX:** Draggable via header; resize from edges/corners.

---

### 1.15 Reschedule All Modal

**Purpose:** Confirm full reschedule (cancel slots, delete proposals).  
**Location:** Scheduling page.

| Content | Description |
|---------|-------------|
| Message | Explains destructive action |
| Buttons | Cancel / Continue (red, destructive) |

**Layout:** Uses shared Modal.  
**UX:** Confirmation before destructive action.

---

### 1.16 Apply All Modal

**Purpose:** Confirm applying all draft proposals.  
**Location:** Scheduling page.

| Content | Description |
|---------|-------------|
| Message | Shows proposal count |
| Buttons | Cancel / Write to job plan |

**Layout:** Uses shared Modal.  
**UX:** Confirmation for batch apply.

---

### 1.17 Discard All Proposals Modal

**Purpose:** Confirm discarding all draft proposals.  
**Location:** Scheduling page.

| Content | Description |
|---------|-------------|
| Message | Explains discard action |
| Buttons | Cancel / Discard All (red) |

**Layout:** Uses shared Modal.  
**UX:** Destructive confirmation.

---

### 1.18 Schedule Preview Modal

**Purpose:** Fullscreen review of draft proposals; apply/reject per proposal or in bulk.  
**Location:** Scheduling page (after generate).

| Section | Content |
|---------|---------|
| Alerts | Late jobs; blocked/skipped; overlaps; validation issues (hard/soft) |
| Toolbar | Apply All, Discard All, Cancel; per-proposal Apply/Reject chips |
| Gantt | Preview schedule with job bars |
| Right panel | Job details when selected; Step schedule with expandable materials per step |

**Layout:** Fullscreen Modal; toolbar; Gantt + right sidebar (~320px).  
**UX:** Color-coded alerts; late job badges; per-proposal Apply/Reject; step materials expandable (“Show materials (N)”).

---

## 2. Sidebars / Panels

### 2.1 Job Details Panel

**Purpose:** Show details and actions for a selected job.  
**Component:** `JobDetailsPanel.jsx`  
**Location:** Jobs page; Scheduling page (Gantt right side).

| Section | Content |
|---------|---------|
| Header | Job ID, status, Product, Priority, Quantity, Deadline |
| Readiness | Badge (Ready now, Ready in ~Xh, etc.) |
| Material shortage | Warning when materials insufficient |
| Earliest completion | When applicable |
| Notes | Free-form notes |
| **Steps** | Ordered list; step name, status, target/done; dependencies; transfer/wait time; **expandable materials per step** (“Show materials (N)”) |
| **Materials (product-level)** | When not shown per-step |
| **Scheduled slots** | Slot cards with machine, times, Start/Pause/Resume, Record Downtime, Cancel |
| Actions | Log Production, Report Delay, Urgent Insert, Edit, Cancel, Duplicate |

**Layout:** Fixed ~320px width; scrollable body; footer with action buttons.  
**UX:** Empty state when no job; status dots; readiness badges; expandable materials per step; duplicate with tooltip (UC-J08).

**Materials per step design:**
- Data sources (in order): `GET /process-steps/:step_id/materials` → explosion API (by_step) → formula ingredients with step_id.
- Display: “Show materials (N)” toggles expand; expanded shows e.g. “MAT-001 (2.5 kg), P-007 (1 ea)”.
- Input materials only (role ≠ output).

---

### 2.2 Scheduling Preview Sidebar

**Purpose:** Job details for a selected proposal in Schedule Preview modal.  
**Location:** Schedule Preview modal, right of Gantt.

| Section | Content |
|---------|---------|
| Header | Job ID, Product, Readiness, Proposal ID, Deadline status |
| Actions | Apply / Reject / Urgent |
| Step schedule | Slot cards: step name, machine, times, duration; **expandable materials per step** |

**Layout:** ~320px panel; same structure as JobDetailsPanel but proposal-specific.  
**UX:** Highlighted slot when Gantt bar selected; per-proposal Apply/Reject; Urgent opens UrgentInsertModal; materials expandable per step.

---

### 2.3 Chat Sidebar

**Purpose:** List of AI chat conversations.  
**Component:** `ChatSidebar.jsx`  
**Location:** AI Assistant modal; AI Chat page.

| Control | Description |
|---------|-------------|
| New Conversation | Primary button |
| Recent Chats | List (title, date) with active state |

**Layout:** 208px; “Recent Chats” section; truncation.  
**UX:** Relative dates; empty state with CTA.

---

### 2.4 AI Chat Panel

**Purpose:** Main AI chat UI.  
**Component:** `AiChatPanel.jsx`

| Control | Description |
|---------|-------------|
| Header | Draggable; Settings, user avatar, Close |
| Error banner | When API errors |
| Messages | User/AI messages; intent/confidence; result cards; assist blocks; proposal blocks |
| Input | Text; Mic, Attach, Search; Send |

**Layout:** Split: ChatSidebar + main area.  
**UX:** “Model active” badge; loading/“Thinking…” state.

---

### 2.5 App Sidebar (Navigation)

**Purpose:** Main app navigation.  
**Component:** `Sidebar.jsx`

| Items | Routes |
|-------|--------|
| Logo | — |
| Dashboard | / |
| Jobs | /jobs |
| Scheduling | /scheduling |
| Production Data | /production-data |
| Predictive Analysis | /predictive |
| Reports | /reports |
| Storage & Inventory | /inventory |
| Products & BOM | /products |
| Machine & Resources | /machines |
| Settings | /settings (bottom) |

**Layout:** 256px; icon + label per item.  
**UX:** Active link highlight; icon fill for active; Settings pinned at bottom.

---

### 2.6 Filter/Sort Panel

**Purpose:** UC-FS01–FS04 — Filter and sort (Jobs, etc.).  
**Component:** `FilterSortPanel.jsx`

| Section | Content |
|---------|---------|
| Filters | Text, select, date (configurable via props) |
| Sort | Sort by; Sort direction (asc/desc) |
| Footer | Reset / Apply Filters |

**Layout:** Slide-out from right, 320px.  
**UX:** Backdrop dismiss; active filter count badge; slide-in animation.

---

## 3. Forms Within Pages

### 3.1 Settings Page

**Sections:**

| Section | Fields / Controls |
|---------|-------------------|
| User Preferences | Theme (ThemeToggle), Language, Timezone |
| Notification Settings | Push Notifications, Email Alerts; “Notify on” (Job Completed, Maintenance Alert, Low Stock Warning, Machine Downtime) |
| System Settings | Simulation Mode, Auto-Save Interval, Data Retention |
| Scheduling | Lock-in window (reschedule), Deviation penalty, Split Strategy, Optimization Objective, Auto-reschedule on Events, Work start time, Work end time, Workdays (Mon–Sat), Public holidays, Refresh work calendars |
| ERP/MES Integration | ERP System, API Endpoint, Test Connection; ErpStatusBadge |
| About | Version info |

**Layout:** PageHeader with Save Now; grid of sections; SettingRow (title, description, control).  
**UX:** Debounced auto-save; Toggle switches; conditional Scheduling section; ERP status badge.

---

### 3.2 Machine Resources Page

| Control | Description |
|---------|-------------|
| Filters | Type, status |
| Actions | Add Machine |
| Table | Machine rows; Edit, Record Downtime, Delete per row |
| Charts | Utilization |

**Forms:** AddMachineModal, RecordDowntimeModal.  
**Layout:** PageHeader; filters; table; charts; modals.

---

### 3.3 Storage & Inventory Page

| Control | Description |
|---------|-------------|
| Tabs | Materials / Expected Arrivals |
| Filters | Search; status; sort |
| Actions | Add Item; Add Expected Arrival |
| Table | Materials with Consume/Receive per row; pagination |

**Forms:** AddItemModal, AddExpectedArrivalModal, ConsumeModal.  
**Layout:** Tabs; toolbar; table; pagination.  
**UX:** Status badges (In Stock, Low Stock, Out of Stock).

---

### 3.4 Products Page

| Control | Description |
|---------|-------------|
| Actions | Add Product |
| Table | Product rows; Edit / BOM actions |

**Forms:** ProductModal, BomModal.  
**Layout:** PageHeader; table; modals.  
**UX:** BOM modal with Process and Formula tabs.

---

### 3.5 Jobs Page

| Control | Description |
|---------|-------------|
| Filters | FilterSortPanel (machine, status, priority, dates, product) |
| Actions | Create Job |
| Content | Job list; JobDetailsPanel when job selected |

**Forms:** CreateJobModal; filter/sort via FilterSortPanel.  
**Layout:** Header; filters; job list; right JobDetailsPanel; FilterSortPanel slide-out.  
**UX:** Toggle JobDetailsPanel; filter count badge.

---

### 3.6 Scheduling Page

| Control | Description |
|---------|-------------|
| Toolbar | Reschedule All, Apply All, Discard All, Urgent Insert |
| Content | Gantt; Job Details sidebar (when in applied view) |
| Modals | Schedule Preview; Reschedule All; Apply All; Discard All; Urgent Insert |

**Layout:** Toolbar; Gantt; side panel; modals.  
**UX:** Bulk actions; preview before apply; step materials in preview sidebar.

---

## 4. Small Windows / Floating UI

### 4.1 Floating Chat Button

**Purpose:** Open AI Assistant modal.  
**Component:** `FloatingChatButton.jsx`  
**Location:** Fixed bottom-right.

| State | Appearance |
|-------|------------|
| Default | Icon (smart_toy); green “active” dot |
| Hover | Expands to show “AI Assistant” label |

**Layout:** Pill-shaped; primary color.  
**UX:** Hover to reveal label; green pulse dot.

---

### 4.2 Tooltips

**Locations:** Hide details, Duplicate job, Late badge, Reject proposal, Drag to reorder, Remove step, Remove ingredient, etc.  
**Implementation:** Native `title` attribute.  
**UX:** No custom tooltip component; inline hints.

---

### 4.3 Action Menus

**Purpose:** Per-row actions (Edit, Delete, Record Downtime, etc.).  
**Layout:** Dropdown or popover from row.  
**UX:** Context-specific; menu closes on action.

---

### 4.4 Toast Notifications

**Purpose:** Short feedback (success, error, info).  
**Implementation:** ToastContext.  
**UX:** Used for save results, errors, scheduling updates.

---

## 5. Shared / Reusable UI Patterns

### 5.1 RefSelect

**Purpose:** Dropdown with API-backed options; supports custom values.  
**Props:** `fetcher`, `value`, `onChange`, `placeholder`, `allowCustom`, etc.  
**Used in:** AddMachineModal, AddItemModal, ProductModal, BomModal.

---

### 5.2 SettingRow

**Purpose:** Settings row with title, description, and control.  
**Props:** `title`, `description`, `children`.  
**Layout:** Two-column; control right-aligned.

---

### 5.3 PageHeader

**Purpose:** Page title and actions.  
**Props:** `title`, `subtitle`, children (actions).  
**Layout:** Title; optional subtitle; action area.

---

### 5.4 Toggle

**Purpose:** Boolean switch (Settings).  
**Props:** `checked`, `onChange`.  
**Layout:** Styled checkbox-like switch.

---

### 5.5 Expandable Materials per Step

**Purpose:** Show materials for a process step without cluttering the UI.  
**Pattern:** “Show materials (N)” button; expands to show list (e.g. “MAT-001 (2.5 kg), P-007 (1 ea)”); “Hide materials” collapses.  
**Used in:** JobDetailsPanel (steps); Scheduling preview sidebar (step cards).  
**Data source:** `GET /process-steps/:step_id/materials` (ProcessStepMaterial); fallback to explosion API or formula ingredients.

---

## 6. Layout and Theming

| Aspect | Description |
|--------|-------------|
| Layout | Sidebar (256px) + main content; Layout wraps Sidebar and outlet |
| Theming | Dark mode via Tailwind; ThemeToggle in Settings; ThemeContext |
| Responsive | `sm:`, `md:` breakpoints; MobileMenu; fullscreen modal insets adjust |
| Consistency | Shared input styles (`inp`); primary color; rounded corners; Material Symbols icons |

---

## 7. Data Sources for Materials per Step

| Source | When Used | Format |
|--------|-----------|--------|
| `GET /process-steps/:step_id/materials` | Primary; when step has `step_id` | ProcessStepMaterial: material_id, product_id, role, quantity_per_unit, unit |
| Explosion API (by_step) | Fallback when available | Materials per step index |
| Formula ingredients (step_id) | Fallback when materials have step_id | material_name, quantity, unit |

Materials are filtered to inputs only (role ≠ output) when displaying.
