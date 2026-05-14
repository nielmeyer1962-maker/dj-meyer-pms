# Project Plan — DJ Meyer Practice Management System

## Goal

Replace the deadline-tracking and assignment work currently scattered across Zoho Projects, spreadsheets, and Daniel's head with a single source of truth for which client owes what to SARS or CIPC, when, and who in the firm is responsible.

## Non-goals

See `CLAUDE.md`. Do not build accounting, CRM, billing, or document management features in any phase before they are explicitly approved.

## Phase 1 — MVP: Client and SARS Deadline Tracker

### Functional scope

**1. Client register**

Add, edit, and archive a client. Fields:

- Legal name and trading name
- Entity type
- Registration number (where applicable)
- Income tax reference number
- VAT number (optional)
- PAYE number (optional)
- Financial year-end (month and day)
- B-BBEE applicable (yes / no)
- Date became a client
- Active flag
- Tax registrations the client holds: Income Tax, VAT, PAYE, Provisional Tax, Dividends Tax

**2. Obligation engine**

For each active client, derive recurring statutory obligations from their entity type, registrations, and year-end. Generate concrete instances with due dates for the current and next twelve months.

**3. Staff assignments**

- A default assignee per obligation type per client.
- Hard rule: every Pty Ltd and CC obligation of type "CIPC Annual Return" is auto-assigned to Tsego.
- Override per instance when needed.

**4. Deadline dashboard**

- Views: this week, next thirty days, overdue.
- Filter by staff member, client, or obligation type.
- Mark instance status: not started, in progress, submitted, completed, on hold.

**5. Manual reminders**

A "notify assignee" button that sends an email via SMTP. No scheduled jobs in Phase 1.

### Obligations to model in Phase 1

| Obligation | Applies to | Frequency | Due date rule (verify each in code) |
|---|---|---|---|
| IRP6 — first provisional | Companies and individuals on provisional | 6-monthly | Last day of month 6 of the tax year |
| IRP6 — second provisional | Same | 6-monthly | Last day of the tax year |
| IRP6 — third (top-up, voluntary) | Same | Annual | 6 months after year-end (companies); 30 September for individuals on Feb year-end |
| ITR14 | Pty Ltd, CC | Annual | 12 months after financial year-end |
| ITR12 | Individuals, trusts | Annual | Per SARS filing season — date varies each year, must be configurable |
| VAT201 | VAT-registered | Monthly or bi-monthly | 25th of the following month on eFiling |
| EMP201 | PAYE-registered | Monthly | 7th of the following month |
| EMP501 — interim | PAYE-registered | Bi-annual | 31 October |
| EMP501 — annual | PAYE-registered | Annual | 31 May |
| CIPC Annual Return | Pty Ltd, CC | Annual | Within 30 business days of incorporation anniversary |
| B-BBEE certificate or affidavit | Where applicable | Annual | Anniversary of last issue |

> **Important:** verify each due-date rule against current SARS or CIPC guidance during implementation. Do not hard-code without a source comment in the file. SARS filing-season dates change yearly; build them as configuration, not constants.

### Out of scope for Phase 1

- Document storage and version control
- Time tracking and billing
- Client portal
- Automated scheduled emails
- n8n or Zoho Projects integration
- Multi-firm or multi-tenant
- SARS eFiling submission integration
- Mobile app

## Phase 2 (sketch only — do not build yet)

- Scheduled reminder emails, driven from n8n or a cron worker
- Zoho Projects two-way sync, so Phase 1 deadlines also appear as Zoho tasks for staff who live in Zoho
- Document drop-zone per obligation instance (proof of submission, working papers)
- Bulk import of clients from existing spreadsheets and Zoho

## Phase 3 (sketch only)

- Dispute resolution case tracker — objection (NOO), appeal (NOA), ADR, Tax Court — with statutory time bars and the kind of document set Daniel already produces (Grounds of Appeal, jurisdictional submissions, etc.)
- B-BBEE share option agreement and affidavit generation
- Time tracking and billing

## Domain model — first cut

```
Client
  - id
  - legal_name, trading_name
  - entity_type (enum)
  - registration_number, tax_ref, vat_number, paye_number
  - year_end (month, day)
  - registrations (set: income_tax, vat, paye, provisional, dividends)
  - bbee_applicable
  - active
  - created_at

StaffMember
  - id, name, role, email, active

Obligation              # the recurring rule for a given client
  - id
  - client_id
  - type (enum: ITR14, IRP6_1, IRP6_2, VAT201, ...)
  - frequency
  - default_assignee_id
  - active

ObligationInstance      # the concrete due item shown on the dashboard
  - id
  - obligation_id
  - period_start, period_end
  - due_date
  - assignee_id
  - status (not_started, in_progress, submitted, completed, on_hold)
  - notes
  - submitted_at, completed_at
```

## Acceptance criteria for Phase 1

- Daniel can add a Pty Ltd client with a March year-end and VAT registration, and within seconds see correctly generated obligations: ITR14, two IRP6s, twelve VAT201s, and one CIPC return — with Tsego on the CIPC one.
- Changing the year-end regenerates future instances without losing any with status other than `not_started`.
- The dashboard shows everything due in the next thirty days for any chosen staff member.
- All deadline calculations are covered by tests.
- A fresh installation can be set up by a developer following the README in under fifteen minutes.

---

## Ticket 3a — Obligation engine foundation (VAT201 only)

**Scope discipline.** Ticket 3 in `KICKOFF_PROMPT.md` covers the whole engine. We are deliberately narrowing 3a to **VAT201 only** so we can prove the model, the business-day machinery, and the generator pattern before adding ITR14 / IRP6 / EMP201 / CIPC. Everything in 3a must be designed so adding those obligations later is a generator + enum addition, not a schema change.

**Authoritative sources for due-date logic (user-verified, do not substitute training data).** Every constant or rule derived from these must carry an inline source comment in the code:

- VAT tax periods (Categories A–E) — `https://www.sars.gov.za/types-of-tax/value-added-tax/tax-periods-for-vat-vendors/` (last updated 31 Jan 2025).
- VAT201 due-date rule (eFiling = last business day of following month; manual = 25th of following month) — `https://www.sars.gov.za/individuals/i-need-help-with-my-tax/calendar/`.
- Weekend / SA public holiday rule: if due date falls on a Saturday, Sunday, or SA public holiday, the obligation is due on the **last business day prior**.

### a) Client model extensions

Two new columns on `clients`. Both nullable at the DB level; cross-field invariants enforced in Python.

| Column | Type | Nullable | Reason |
|---|---|---|---|
| `vat_category` | Enum (`A`, `B`, `C`, `D`, `E`) | Yes | SARS assigns each VAT vendor exactly one category. Drives period-end months. Nullable because non-VAT-registered clients have no category, and because a newly-registered VAT vendor may not yet have a category recorded in the firm's system. |
| `vat_submission_method` | Enum (`EFILING`, `MANUAL`) | Yes | Determines whether the due date is "last business day of following month" or "25th of following month". Nullable for the same reasons. |

**Invariants to enforce (final, per Daniel's Ticket 3a decisions):**

- If `has_vat` is `False` → both `vat_category` and `vat_submission_method` **MUST** be `None`.
- If `has_vat` is `True` → both **MAY** be `None` (newly-registered vendor whose details are not yet captured).
- **Pairing rule (independent of `has_vat`):** if one of the two VAT fields is set, the other must also be set. They are either both `None` or both non-`None`.
- An `@validates` decorator alone cannot reliably enforce these (it fires per-attribute and depends on attribute-assignment order). Reuse the **`before_insert` / `before_update` event-listener pattern** already established for `year_end_month` / `year_end_day` pairing in `app/models/client.py`. Add a single listener that checks all three rules together.
- Add per-attribute `@validates` only to catch obviously invalid singletons (e.g. setting `vat_category` to a string not in the enum). Cross-field checks belong in the event listener.

**Consequence for the generator:** the VAT201 generator must treat "has_vat=True with category=None or method=None" as an incomplete-data case and return `[]` early (same as the non-VAT case). This is already covered in the pre-conditions in section (d).

**Migration:** single Alembic revision that adds the two columns. Existing rows are non-VAT (`has_vat=False`) so backfill is unnecessary — verify before writing the migration.

### b) `ObligationInstance` model

New table `obligation_instances`. Designed so adding EMP201/IRP6/etc. later is just an enum value + new generator function.

| Column | Type | Nullable | Default | Reason |
|---|---|---|---|---|
| `id` | Integer PK | No | autoincrement | Standard surrogate key. |
| `client_id` | Integer FK → `clients.id` | No | — | Every obligation belongs to a client. ON DELETE behaviour: **RESTRICT** (we should not lose a client's submitted-return history because of an accidental delete). Archive via `clients.active=False` instead. |
| `obligation_type` | Enum (`VAT201` for now) | No | — | Discriminator. Phase 1 will eventually hold `VAT201`, `EMP201`, `EMP501_INTERIM`, `EMP501_ANNUAL`, `IRP6_1`, `IRP6_2`, `IRP6_3`, `ITR14`, `ITR12`, `CIPC_ANNUAL`, `BBEE`. We add only `VAT201` in 3a; the enum is defined in a separate `app/models/obligation.py` module so future additions don't touch `client.py`. |
| `period_start` | Date | No | — | First day of the tax period. For Cat C December 2025, this is 2025-12-01. |
| `period_end` | Date | No | — | Last day of the tax period. Critical for the unique constraint and for VAT201 due-date calculation. |
| `submission_due_date` | Date | No | — | When the return must be filed. For VAT201 == `payment_due_date`. We keep them separate now because future obligations (e.g. provisional tax) have distinct submission and payment dates. |
| `payment_due_date` | Date | No | — | When payment is due. For VAT201 == `submission_due_date`. |
| `status` | Enum (`PENDING`, `SUBMITTED`, `PAID`, `EXEMPT`) | No | `PENDING` | Lifecycle. `OVERDUE` is **derived at read time**, not stored — see state-graph notes below. |
| `generated_at` | DateTime (UTC, tz-aware) | No | `func.now()` | When the engine produced this row. Useful for "regenerate" semantics. |
| `updated_at` | DateTime (UTC, tz-aware) | No | `func.now()`, `onupdate=func.now()` | Standard. |

**State graph (final, per Daniel's Ticket 3a decisions):**

- Linear: `PENDING → SUBMITTED → PAID`. No skipping; `PAID` is not reachable from `PENDING` directly.
- `EXEMPT` is a terminal off-ramp from any non-terminal state, for cases like mid-year VAT deregistration where the future instance should be preserved but is no longer applicable.
- `OVERDUE` is **not** a stored status. Read-time predicate: `status == PENDING AND submission_due_date < today_in_Africa_Johannesburg`. No nightly job, no scheduled work in Phase 1. The dashboard view applies this predicate when querying.
- Enforce the state graph in the service layer (a transition function), not in the DB. Direct ORM writes will not be guarded — service layer is the only legitimate caller for status changes.

**Regenerate semantics (final, per Daniel's Ticket 3a decisions):**

- The regenerate operation **recalculates** due dates for `PENDING` instances rather than snapshotting them at original generation time.
- If a client switches `vat_submission_method` from `EFILING` to `MANUAL` (or vice versa) mid-year, the next regenerate updates the `submission_due_date` / `payment_due_date` of all `PENDING` rows for that client to reflect the new method.
- `SUBMITTED`, `PAID`, and `EXEMPT` rows are immutable to regenerate — their dates reflect what was true when they were submitted/paid/exempted.
- The actual regenerate-with-preservation service is **Ticket 3c**, not 3a. 3a only specifies that the unique constraint enables it.

**Indexes and constraints:**

- `UNIQUE (client_id, obligation_type, period_end)` — prevents the generator from creating duplicates when re-run. This is the idempotency key.
- Index on `(status, submission_due_date)` — supports the dashboard query "what's due in the next 30 days that is not yet submitted" and the derived `OVERDUE` predicate.
- Index on `client_id` (Postgres creates one for the FK automatically, but we make it explicit so it survives DB-engine changes).
- No index on `assignee_id` — column does not exist in 3a (assignment is Ticket 3b). The dashboard's "by staff member" filter is deferred.

**No `notes` column in 3a.** PROJECT_PLAN.md's first-cut domain model includes `notes`. Deferred to 3b when we wire the UI; not needed by the generator.

### c) Business-day helper module — `app/utils/business_days.py`

New module. Function signatures only in 3a; implementation in the same ticket once signatures are approved.

```python
from datetime import date

def is_business_day(d: date) -> bool: ...
def last_business_day_of_month(year: int, month: int) -> date: ...
def shift_to_prior_business_day(d: date) -> date: ...
```

**Implementation notes (for the code-writing turn, not now):**

- **Dependency (approved):** add `holidays>=0.50` to `requirements.txt`. The package's `holidays.country_holidays("ZA")` returns a dict-like with all gazetted SA public holidays and applies the §2(1) "Sunday → Monday observed" rule of the Public Holidays Act 36 of 1994. Verify on first use by spot-check: `holidays.country_holidays("ZA")[date(2026, 4, 27)]` should return "Freedom Day" and `[date(2026, 8, 10)]` should return a "Women's Day (observed)" record (because 9 Aug 2026 is a Sunday).
- One-off proclaimed holidays (e.g. election days the President gazettes) are added in `holidays` releases. Document in the README that the package should be kept current.
- `is_business_day(d)`: returns `False` if `d.weekday() in (5, 6)` (Sat/Sun) or `d` is in the SA holiday set for `d.year`; otherwise `True`.
- `last_business_day_of_month(year, month)`: start from `date(year, month, calendar.monthrange(year, month)[1])` and call `shift_to_prior_business_day`.
- `shift_to_prior_business_day(d)`: walk backwards one day at a time until `is_business_day` is true. Bounded loop — at most 7 + a few holiday days; cap defensively at 14 iterations and raise if exceeded (signals a bug or a holiday-data problem).
- **Holiday cache (final, per Daniel's Ticket 3a decisions):** module-level `dict[int, set[date]]` keyed by year. Each year's holiday set is built lazily on first access for that year, then cached. Generator queries spanning multiple years (e.g. a 12-month window crossing a year boundary) hit two cache entries, not one shared mutable set — avoids cross-year pollution and makes per-year invalidation trivial if we ever need it.

### d) VAT201 generator — `app/services/obligations/vat201.py`

Signature:

```python
def generate_vat201(client: Client, months_ahead: int = 12) -> list[ObligationInstance]: ...
```

Returns instances **without** committing them — caller (a future service-layer function in 3c) decides whether to `session.add_all()` and commit, or diff against existing rows to avoid the unique-constraint violation. This keeps the function pure and testable.

**Pre-conditions (return `[]` early):**

- `client.has_vat` is `False`, OR
- `client.vat_category` is `None`, OR
- `client.vat_submission_method` is `None`.

(The pairing rule from section (a) means `category=None XOR method=None` is impossible at the DB level, but the generator still checks both defensively.)

**Generation logic in prose** (no code):

For each category, the generator identifies the set of **period-end dates** that fall within the window `[today, today + months_ahead months]`, then for each period-end computes the due date per the submission method, then constructs an `ObligationInstance` with `period_start` = first day of the period, `period_end` = the period-end date, and `submission_due_date` = `payment_due_date` = the computed due date.

- **Category A (bi-monthly, odd-end-months Jan/Mar/May/Jul/Sep/Nov):** walk forward from the current month; for every month whose number is in `{1, 3, 5, 7, 9, 11}`, the period ends on the last calendar day of that month and starts on the first day of the previous month (a two-month period). Example: period ending 31 May 2026 → period_start = 1 Apr 2026.
- **Category B (bi-monthly, even-end-months Feb/Apr/Jun/Aug/Oct/Dec):** same as Cat A but with `{2, 4, 6, 8, 10, 12}`. Period ending 30 Apr 2026 → period_start = 1 Mar 2026.
- **Category C (monthly, mandatory turnover > R30m):** every calendar month. Period ending 31 Dec 2025 → period_start = 1 Dec 2025.
- **Category D (six-monthly, Feb and Aug ends):** generate periods ending the last day of Feb and of Aug only. Period ending 31 Aug 2026 → period_start = 1 Mar 2026 (six-month period).
- **Category E (annual):** **`NotImplementedError("Category E pending domain confirmation")` — approved placeholder per Ticket 3a decisions.** Write a failing test that asserts the exception is raised so we are forced to revisit when a Cat E vendor is captured.

**Due-date calculation, regardless of category:**

- If `vat_submission_method == EFILING`: due = `last_business_day_of_month(following_year, following_month)`, where `following_month = (period_end.month % 12) + 1` and `following_year = period_end.year + 1 if period_end.month == 12 else period_end.year`. Already returns a business day, so no further shift.
- If `vat_submission_method == MANUAL`: candidate = `date(following_year, following_month, 25)`. Apply `shift_to_prior_business_day(candidate)`.

### e) Test cases — primary date-pair verification

Place in `tests/services/obligations/test_vat201.py`. Day-of-week and SA holiday workings shown so the test docstring can cite them.

| # | Category | Method | Period end | Naïve following-month date | Shift applied? | **Expected due date** |
|---|---|---|---|---|---|---|
| 1 | B | eFiling | 30 Apr 2026 | 31 May 2026 (last day of May) | Yes — 31 May is **Sunday**, 30 May Sat, **29 May Fri** is a business day | **29 May 2026** |
| 2 | B | Manual | 30 Apr 2026 | 25 May 2026 | No — 25 May 2026 is **Monday**, business day, no SA holiday | **25 May 2026** |
| 3 | A | eFiling | 31 Jan 2026 | 28 Feb 2026 (last day of Feb, 2026 not a leap year) | Yes — 28 Feb is **Saturday**, **27 Feb Fri** is a business day | **27 Feb 2026** |
| 4 | C | Manual | 31 Dec 2025 | 25 Jan 2026 | Yes — 25 Jan 2026 is **Sunday**, 24 Jan Sat, **23 Jan Fri** is a business day | **23 Jan 2026** |
| 5 | A | Manual | 30 Nov 2026 | 25 Dec 2026 | Yes — 25 Dec 2026 is **Christmas Day**, a SA public holiday (Friday); **24 Dec 2026 Thu** is a business day | **24 Dec 2026** |

Test case 5 is the natural holiday-shift case — no `today`-mocking needed. The synthetic "mock today" test from the earlier draft is **dropped**.

**Additional tests required to round out the suite:**

- Category C, eFiling, period ending 31 Dec 2025 → last business day of January 2026 (31 Jan 2026 is a Saturday → 30 Jan Fri, no holiday → **30 Jan 2026**). Verifies the year-rollover branch in due-date calculation.
- Pre-condition tests: `has_vat=False` returns `[]`; `vat_category=None` returns `[]`; `vat_submission_method=None` returns `[]`.
- Idempotency test at the service-layer level (Ticket 3c, not 3a): running the generator twice and persisting must not duplicate rows — verifies the unique constraint.
- Category E test: asserts `NotImplementedError("Category E pending domain confirmation")` is raised.
- State-graph test (Ticket 3b, not 3a, but flagged here): cannot go `PENDING → PAID` directly; can go any non-terminal → `EXEMPT`.

### Out of scope for Ticket 3a (deferred to 3b and beyond)

- Staff assignment to obligation instances. No `assignee_id` column yet (Ticket 3b).
- The dashboard UI. The generator returns objects; no view layer (Ticket 3b).
- Other obligation types (EMP201, IRP6, ITR14, ITR12, CIPC, B-BBEE).
- The regenerate-with-preservation service that recalculates `PENDING` rows when client config changes while leaving `SUBMITTED` / `PAID` / `EXEMPT` rows untouched (Ticket 3c).
- Scheduled emails / notifications (Phase 2).

### Decisions locked in for Ticket 3a (per Daniel)

1. Client invariants: `has_vat=False` → both VAT fields **must** be `None`; `has_vat=True` → both **may** be `None`; pairing rule applies in all cases (both set or both `None`).
2. `ObligationInstance.status` enum is `PENDING`, `SUBMITTED`, `PAID`, `EXEMPT`. `OVERDUE` is derived at read time. State graph is linear `PENDING → SUBMITTED → PAID`; `EXEMPT` is a terminal off-ramp.
3. Regenerate **recalculates** `PENDING` rows; it does not snapshot. `SUBMITTED` / `PAID` / `EXEMPT` are immutable to regenerate.
4. No `notes` column in 3a.
5. `holidays>=0.50` approved as a dependency.
6. Category E raises `NotImplementedError("Category E pending domain confirmation")` until a Cat E vendor is on the books.
7. Test suite includes Cat A + Manual + period end 30 Nov 2026 → 24 Dec 2026 as the natural holiday-shift case. No mock-`today` test.
8. Holiday cache is a module-level `dict[int, set[date]]` keyed by year, lazily populated.

---

## Ticket 3b — Service layer, assignment, and minimum dashboard

**Scope discipline.** Ticket 3a landed the *engine* — Client VAT fields, `ObligationInstance` schema, business-day helper, and the VAT201 generator that produces rows. 3b makes those rows usable:

1. A service-layer state machine that walks an instance `PENDING → SUBMITTED → PAID` with `EXEMPT` as a terminal off-ramp from any non-terminal state. (B1)
2. A read-time `OVERDUE` predicate keyed off Africa/Johannesburg today, with a small `today_sast()` utility so no module sprinkles `zoneinfo` calls. (B2)
3. A `Staff` model and an `assignee_id` FK on `ObligationInstance` so we know who's responsible. (B3)
4. A minimum-viable dashboard that lists what's due and lets the user mark progress and reassign. (B4)
5. The cross-cutting fix that wires `vat_category` and `vat_submission_method` into the existing client form — without it the generator returns `[]` for every freshly-created client and the dashboard would be empty until someone hand-edits the DB. (Cross-cutting)

Anything beyond the basic "what's due / mark done" loop — bulk operations, scheduled email notifications, calendar / iCal export, custom date pickers, per-obligation detail pages, user accounts, n8n / Zoho integration — defers to 3c+.

**Time-zone note (cross-cutting).** Stored timestamps remain UTC tz-aware per the 3a convention. Only the `OVERDUE` "today" comparison and any user-facing display shift to Africa/Johannesburg — a deadline reached at 23:59 SAST is not overdue at 22:00 UTC the next day. Implementation lives in a new `app/utils/dates.py` (B2 introduces it) and is reused by the dashboard view layer.

**Builds directly on 3a.** No 3a invariant is loosened. The state graph is service-layer-only per 3a decision 2; the model retains `status` defaulting to `PENDING` at INSERT and `nullable=False`; the VAT201 generator is unchanged. The only model schema additions in 3b are an `assignee_id` FK on `ObligationInstance` (B3) and a new `staff` table (B3). The `notes` column considered earlier is deferred entirely to 3c.

### B1) State-graph transition service — `app/services/obligations/transitions.py`

A new module that is the **SOLE GUARDIAN** of the linear `PENDING → SUBMITTED → PAID` lifecycle, with `EXEMPT` as a terminal off-ramp from any non-terminal state. The 3a decision stands unchanged: NO DB `CHECK` constraint, NO `before_update` listener guarding status — direct ORM writes remain unguarded so an admin can correct a SARS retroactive cancellation (e.g. walk a `PAID` row back to `EXEMPT`) without fighting a guard. The transition service is the documented happy path; direct ORM writes are the documented escape hatch.

**Decisions:**

1. **API shape — free module-level functions.** Three exports: `mark_submitted(instance)`, `mark_paid(instance)`, `mark_exempt(instance)`. Each mutates the passed instance in place and returns `None`; the caller controls the session. Free functions over methods on the model so the "service layer owns behaviour, model owns shape" boundary stays clean.
2. **Transition metadata — none in 3b.** No `submitted_at`, `confirmation_number`, `payment_reference`, or `notes` parameters. `updated_at` already captures "when state changed" via `onupdate=func.now()`. Richer audit fields are 3c material; optional kwargs can be added later without breaking existing call sites.
3. **Idempotency — ValueError, not no-op.** `mark_submitted` on an already-`SUBMITTED` instance raises `ValueError`. Silent no-op hides bugs (double-submit, racing tabs); an error surfaces the incorrect call path. The dashboard pre-checks status before rendering each row's action buttons, so legitimate flows don't reach this branch.
4. **Single-instance only in 3b.** No bulk variant. Bulk needs real demand before being designed well — defer to 3c+.

**Proposed signatures:**

```python
def mark_submitted(instance: ObligationInstance) -> None:
    """PENDING → SUBMITTED. Raises ValueError if instance.status is not PENDING."""

def mark_paid(instance: ObligationInstance) -> None:
    """SUBMITTED → PAID. Raises ValueError if instance.status is not SUBMITTED."""

def mark_exempt(instance: ObligationInstance) -> None:
    """Any non-terminal → EXEMPT. Raises ValueError if instance.status is PAID or EXEMPT."""
```

All three mutate `instance.status` in place. None touch `updated_at` — the model's `onupdate=func.now()` handles that at flush. None call `db.session.commit()`; the caller (a Flask route) owns the commit.

**Legal transitions:**

| From → To | `mark_submitted` | `mark_paid` | `mark_exempt` |
|---|---|---|---|
| PENDING | ✓ | ValueError | ✓ |
| SUBMITTED | ValueError | ✓ | ✓ |
| PAID | ValueError | ValueError | ValueError |
| EXEMPT | ValueError | ValueError | ValueError |

**Tests for B1 (`tests/services/obligations/test_transitions.py`):**

- `mark_submitted` on PENDING advances state.
- `mark_paid` on SUBMITTED advances state.
- `mark_exempt` from PENDING advances state.
- `mark_exempt` from SUBMITTED advances state.
- `mark_submitted` on SUBMITTED/PAID/EXEMPT raises ValueError with the prior state in the message.
- `mark_paid` on PENDING/PAID/EXEMPT raises ValueError.
- `mark_exempt` on PAID/EXEMPT raises ValueError.
- Sanity: after `mark_submitted` then commit, `updated_at` is strictly later than `generated_at` (uses the existing model behaviour; this test guards against an accidental refactor that breaks it).

Error message convention:

```
ValueError: cannot mark_submitted on ObligationInstance(id=42, status=SUBMITTED); legal prior state is PENDING.
```

— includes the id, current status, and the legal prior state(s). Helps the dashboard's flash message be informative without the route layer doing string construction.

### B2) OVERDUE derived predicate — `app/services/obligations/predicates.py` + `app/utils/dates.py`

`OVERDUE` is **never stored**; it's a read-time predicate: `status == PENDING AND submission_due_date < today_in_Africa_Johannesburg`. Strict `<` per the 3a §(b) state-graph note — a row whose `submission_due_date` equals today is "due today", not "overdue".

The dashboard needs the predicate in two evaluation contexts:

- **SQL** — `WHERE` clause for "show me only overdue items".
- **Python** — per-row flag for "render this row in red".

**Decisions:**

1. **Two co-located service functions, NOT a `hybrid_property`.** `is_overdue(instance, today) -> bool` for Python eval; `overdue_filter(today) -> ColumnElement[bool]` for SQL eval. The predicate depends on `today`, a runtime value rather than a column, so the `hybrid_property.expression()` half would need a class-method shim that obscures the call site. Two explicit functions are clearer than the magic. Same "service layer owns behaviour, model owns shape" boundary as B1.
2. **`today_sast()` lives in `app/utils/dates.py`.** Single function using stdlib `zoneinfo.ZoneInfo("Africa/Johannesburg")`. Mirrors the `app/utils/business_days.py` pattern — small, focused utility module. Avoid pytz (deprecated). One central place to patch if the zone string ever needs to change; clean to mock in tests via monkeypatch.
3. **`today` is always a required parameter** on `is_overdue`/`overdue_filter` — callers pass `today_sast()` explicitly. Same pattern as `generate_vat201(today=...)`. Removes implicit module-level state from unit tests.

**Proposed signatures:**

```python
# app/utils/dates.py
from datetime import date, datetime
from zoneinfo import ZoneInfo

_SAST = ZoneInfo("Africa/Johannesburg")


def today_sast() -> date:
    """Today in Africa/Johannesburg.

    Used wherever a deadline 'today' applies — a deadline reached at 23:59 SAST
    is not overdue at 22:00 UTC the next day.
    """
    return datetime.now(_SAST).date()
```

```python
# app/services/obligations/predicates.py
from datetime import date

from sqlalchemy import ColumnElement, and_

from app.models.obligation import ObligationInstance, ObligationStatus


def is_overdue(instance: ObligationInstance, today: date) -> bool:
    """OVERDUE iff status == PENDING AND submission_due_date < today (Python eval)."""
    return (
        instance.status is ObligationStatus.PENDING
        and instance.submission_due_date < today
    )


def overdue_filter(today: date) -> ColumnElement[bool]:
    """OVERDUE iff status == PENDING AND submission_due_date < today (SQL eval)."""
    return and_(
        ObligationInstance.status == ObligationStatus.PENDING,
        ObligationInstance.submission_due_date < today,
    )
```

**Tests for B2 (`tests/utils/test_dates.py` and `tests/services/obligations/test_predicates.py`):**

For `today_sast()`:

- Returns a `date` (smoke).
- Mock `datetime.now(...)` to a known UTC instant straddling midnight SAST — e.g. 21:59 UTC and 22:01 UTC on the same UTC day should return *different* dates (SAST = UTC+2). Guards against accidentally using UTC date everywhere.

For `is_overdue(instance, today)`:

- PENDING + `due < today` → True.
- PENDING + `due == today` → False (strict `<` boundary).
- PENDING + `due > today` → False.
- SUBMITTED + `due < today` → False.
- PAID + `due < today` → False.
- EXEMPT + `due < today` → False.

For `overdue_filter(today)`:

- Seed a small fixture: one PENDING-past, one PENDING-today, one PENDING-future, one SUBMITTED-past, one PAID-past, one EXEMPT-past. Query with `overdue_filter(today)`; assert exactly the PENDING-past row is returned. Confirms the SQL predicate matches the Python predicate semantically — a divergence between them would be a silent dashboard bug.

### B3) Staff model + `assignee_id` FK on `ObligationInstance` — `app/models/staff.py`

A new `staff` table records people who can be assigned obligation work; `obligation_instances` gains a nullable `assignee_id` FK so the dashboard knows whose work each row is. Staff is intentionally NOT a `User` — 3b doesn't introduce login or auth. When auth lands later, `User` will be a separate model that *references* `Staff` (probably 1:1 by code or by FK).

**Decisions:**

1. **Staff field set:**

   | Column | Type | Nullable | Notes |
   |---|---|---|---|
   | `id` | Integer PK | No | autoincrement |
   | `code` | varchar 16 | No, **unique** | Human identifier — `NIEL`, `CANDI`, `TSEGO`, etc. Validation: non-empty, no surrounding whitespace |
   | `full_name` | varchar 200 | No | Display name |
   | `email` | varchar 200 | Yes | For the future notify-assignee feature. Lands now so we don't migrate again immediately. No `@` shape check in 3b. |
   | `role` | Enum `StaffRole` | No | Values `TAX`, `SECRETARIAL`, `BOTH` |
   | `active` | Boolean | No, default True | Soft delete via `active=False`; preferred over hard delete |
   | `created_at` | DateTime(tz=True) | No | `server_default=func.now()`. Stored UTC; display in Africa/Johannesburg |

   `StaffRole` includes `BOTH` because the firm genuinely has cross-domain staff (Tsego, Daniel). Out of B3: `phone`, `start_date`, `staff_number`, `cost_centre`, password / auth fields.

2. **Staff vs User — separate.** 3b ships Staff only. The dashboard's "filter by assignee" surfaces all *active* staff regardless of any login concept. When User authentication lands later, the User model will reference Staff (rather than the reverse).
3. **`assignee_id` nullable — YES.** Newly-generated obligations for a client whose engagement-rep mapping isn't captured yet show up as `assignee_id IS NULL`. The dashboard surfaces "Unassigned" as a filter category — feature, not edge case.
4. **ON DELETE on `assignee_id` — `SET NULL`, not `RESTRICT`.** Staff offboarding is a normal event. With `RESTRICT`, hard-deleting a staff record requires manually reassigning every row of their open work first. With `SET NULL`, deleting a staff record reverts their open obligations to "unassigned"; the dashboard surfaces them as actionable for whoever picks them up. Soft delete via `active=False` is the recommended routine path (preserves history); SET NULL is the right hard-delete semantics.

**Schema additions:**

- New table `staff` (the seven columns above).
- New column `obligation_instances.assignee_id` — `Integer`, nullable, `ForeignKey("staff.id", ondelete="SET NULL")`, `index=True`.

**Migration:** single Alembic revision adding `staff` + `obligation_instances.assignee_id`. With `render_as_batch=False` now set (post-3a env.py cleanup), `op.create_table('staff', …)` triggers `CREATE TYPE staffrole` implicitly via Postgres ENUM; the `assignee_id` column is `Integer` (not Enum), so no separate type-creation step is needed. Expect a clean autogenerated migration — no hand-fix like 3a Chunk 1.

**Proposed model code:**

```python
# app/models/staff.py
from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.extensions import db


class StaffRole(enum.Enum):
    TAX = "TAX"
    SECRETARIAL = "SECRETARIAL"
    BOTH = "BOTH"


class Staff(db.Model):
    __tablename__ = "staff"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[str | None] = mapped_column(String(200))
    role: Mapped[StaffRole] = mapped_column(Enum(StaffRole), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Stored UTC; display in Africa/Johannesburg when shown to users
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    @validates("code")
    def _validate_code(self, key: str, value: str) -> str:
        if not value or not value.strip() or value != value.strip():
            raise ValueError("code is required, non-blank, and must not have surrounding whitespace")
        return value

    @validates("full_name")
    def _validate_full_name(self, key: str, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("full_name is required and cannot be blank")
        return value

    def __repr__(self) -> str:
        return f"<Staff {self.code} {self.full_name!r} role={self.role.name}>"
```

**Change to `ObligationInstance`:**

```python
# add to app/models/obligation.py
assignee_id: Mapped[int | None] = mapped_column(
    Integer,
    ForeignKey("staff.id", ondelete="SET NULL"),
    nullable=True,
    index=True,
)
```

**Tests for B3:**

- `tests/test_staff_model.py`:
  - Round-trip persist with all required fields.
  - `code` unique constraint: persisting a duplicate raises `IntegrityError`.
  - `code` blank or whitespace-padded raises `ValueError` at construction (via `@validates`).
  - `full_name` blank raises `ValueError`.
  - All three `StaffRole` values persist.
  - `active` defaults to True.
  - `email` accepts None.
- Additions to `tests/test_obligation_model.py`:
  - `assignee_id` nullable: persist an `ObligationInstance` with `assignee_id=None`.
  - `assignee_id` with a valid `staff.id` persists; the FK is satisfied.
  - **Runtime `SET NULL`** test: create staff + obligation with `assignee_id=staff.id`, hard-delete the staff row, verify the obligation's `assignee_id` is now `None`. Requires SQLite FK enforcement (next item).

**Infrastructure change (locked):** `tests/conftest.py` gains a `connect`-event listener that issues `PRAGMA foreign_keys = ON` on the test SQLite engine so SET NULL fires at runtime. Side benefit: the 3a `client_id` RESTRICT FK gets real runtime teeth too.

### B4) Dashboard UI — `app/dashboard/` blueprint

The first user-visible surface. One page that lists what's due and lets the user mark progress or reassign. Wires together everything from 3a (the generated rows), B1 (the transition service), B2 (the OVERDUE predicate + `today_sast()`), B3 (Staff + `assignee_id`), and the cross-cutting client-form fix (so there's actually data to display).

**Decisions:**

1. **One page with filters, NOT multiple pages.** URL: `/dashboard/`. Multiple pages would be the same data sliced differently — one page lets the user *compose* slices ("Niel's overdue items").
2. **Three AND-combined filters:**

   | Filter | Choices | Notes |
   |---|---|---|
   | **Status** | All / PENDING / SUBMITTED / PAID / EXEMPT | Stored-status only — no "OVERDUE" choice here. OVERDUE lives in the View filter. |
   | **Assignee** | All / Unassigned / [active staff codes] | Populated dynamically from `Staff` where `active=True`. "Unassigned" matches `assignee_id IS NULL`. |
   | **View** | All / Due this week / Due next 30 days / Overdue | Date-scoped derived slices. "Due this week" = `submission_due_date BETWEEN today AND today+7`. "Overdue" composes `overdue_filter(today)` from B2. |

   Deferred from 3b filtering: by client, by obligation_type (only VAT201 exists today), custom date range with date pickers.

3. **Sort `submission_due_date ASC, client.legal_name ASC`.** Most urgent at top, stable secondary sort by client legal name. No pagination — ~120 rows/year is well under any pagination threshold.
4. **Per-row actions are inline buttons (NOT a dropdown menu), with `Reassign` opening a modal.**

   | Row status | Visible action buttons |
   |---|---|
   | `PENDING` | "Mark submitted" + "Mark exempt" + "Reassign" |
   | `SUBMITTED` | "Mark paid" + "Mark exempt" + "Reassign" |
   | `PAID` or `EXEMPT` | (none — terminal states; the row is read-only via the dashboard. Admin overrides via direct ORM per the 3a state-graph decision.) |

   Each "Mark …" action is a tiny `<form method="post">` with CSRF; on submit the route calls the matching B1 function. `ValueError` from B1 is caught and surfaced as `flash("…", "danger")`. Reassign opens a Bootstrap 5 modal whose dropdown contains "— Unassigned —" plus every active staff member by `code` + `full_name`. **Implementation: one shared modal at the bottom of the page + ~10 lines of vanilla JS to populate the hidden `obligation_id` and modal title when a row's "Reassign" trigger is clicked.** Avoids ~50× duplicated modal HTML. OVERDUE shows as a red badge inline on the row's status column (rendered when `is_overdue(instance, today_sast())` is True); it's not a button.

5. **Mobile-friendly via Bootstrap 5.3 `.table-responsive`** plus `.btn-group-sm` for touch-friendly button size. No card-layout fallback in 3b; reassess if Daniel's phone usage shows the table is awkward.
6. **`notes` column from 3a — DEFERRED ENTIRELY to 3c** (locked-in decision). Nothing about notes in the schema, the dashboard, or the reassign modal in 3b.

**Files to create:**

- `app/dashboard/__init__.py` — empty package marker.
- `app/dashboard/routes.py` — one `GET /` + four `POST` action endpoints.
- `app/dashboard/forms.py` — `ReassignForm`.
- `app/templates/dashboard/list.html` — filter panel above a table, action buttons inline, one shared reassign modal at the bottom.
- `tests/dashboard/__init__.py` — empty.
- `tests/dashboard/test_routes.py` — see test list below.

**Files modified:**

- `app/__init__.py` — register the new blueprint.
- `app/templates/base.html` — add a nav link to `/dashboard/`.

**Proposed route signatures:**

```python
bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


@bp.get("/")
def list_obligations(): ...


@bp.post("/obligations/<int:obligation_id>/mark-submitted")
def mark_obligation_submitted(obligation_id: int): ...


@bp.post("/obligations/<int:obligation_id>/mark-paid")
def mark_obligation_paid(obligation_id: int): ...


@bp.post("/obligations/<int:obligation_id>/mark-exempt")
def mark_obligation_exempt(obligation_id: int): ...


@bp.post("/obligations/<int:obligation_id>/reassign")
def reassign_obligation(obligation_id: int): ...
```

All POST handlers follow the same shape: `db.get_or_404`, call B1 (or set `assignee_id` for reassign), `ValueError` → `flash("…", "danger")` and no commit, success → `db.session.commit()` + `flash("…", "success")`, then `redirect(url_for("dashboard.list_obligations", **request.args))` (preserves filter state across actions).

**Filter form approach — raw query-string parsing, not WTForms.** The filters are three `<select>`s with a vanilla `<button type="submit">`. WTForms adds ceremony with no validation payoff (every filter value is server-validated against an enum/staff lookup anyway). `ReassignForm` does use Flask-WTF — for CSRF.

**Tests for B4 (`tests/dashboard/test_routes.py`):**

- `GET /dashboard/` renders 200 and lists all obligations (smoke).
- `GET /dashboard/?status=PENDING` returns only `PENDING` rows.
- `GET /dashboard/?assignee=NIEL` returns only rows assigned to staff code `NIEL`.
- `GET /dashboard/?assignee=__unassigned__` returns only rows with `assignee_id IS NULL`.
- `GET /dashboard/?view=overdue` returns only rows matching `overdue_filter(today_sast())`; tests inject `today` via monkey-patching `today_sast` to a frozen date.
- `GET /dashboard/?view=this_week` returns only rows with `submission_due_date` in `[today, today+7]`.
- `POST .../mark-submitted` on PENDING advances to `SUBMITTED`, commits, redirects, success flash.
- `POST .../mark-submitted` on SUBMITTED: no state change, danger flash echoing the B1 error message, no commit.
- `POST .../mark-paid` on SUBMITTED advances; on PENDING flashes.
- `POST .../mark-exempt` on PENDING and on SUBMITTED both advance to `EXEMPT`; on `PAID` flashes.
- `POST .../reassign` with a valid `assignee_id` updates the row; with `""` (Unassigned) sets `assignee_id=None`; with a non-existent staff id rejects.
- CSRF: a POST without the token returns 400.
- **Filter-state preservation across actions.** `POST .../mark-submitted` from a filtered list URL → assert the redirect Location contains the same query string.

### Cross-cutting: VAT fields on the existing client form

Without this, the generator returns `[]` for any client whose `vat_category` or `vat_submission_method` is `None`, and those fields can't be set anywhere in the current UI. **In scope for 3b.**

**Files modified:**

- `app/clients/forms.py` — add two `SelectField`s and extend `ClientForm.validate()` with the VAT pairing rules.
- `app/clients/routes.py` — wire the new form fields in `create_client` and `edit_client`, using the existing `EntityType[name]` lookup pattern.
- `app/templates/clients/form.html` — render the two new fields in the existing layout.

**Form changes:**

```python
# app/clients/forms.py (additions only)
from app.models.client import EntityType, VatCategory, VatSubmissionMethod


class ClientForm(FlaskForm):
    # ... existing fields ...

    vat_category = SelectField(
        "VAT category",
        choices=[("", "—")] + [(c.name, c.name) for c in VatCategory],
        validators=[validators.Optional()],
    )
    vat_submission_method = SelectField(
        "VAT submission method",
        choices=[
            ("", "—"),
            (VatSubmissionMethod.EFILING.name, "eFiling"),
            (VatSubmissionMethod.MANUAL.name, "Manual"),
        ],
        validators=[validators.Optional()],
    )
```

Display formatting is form-layer-only per the 3a decision (uppercase storage values, mixed-case UI labels). The `VatCategory` letters need no formatting.

**Cross-field validation extension** — append to the existing `ClientForm.validate()`:

```python
def validate(self, extra_validators=None):
    if not super().validate(extra_validators):
        return False

    # ... existing year-end pairing block ...

    # VAT field invariants — mirror the model's _check_pairing_invariants:
    cat = self.vat_category.data or None
    method = self.vat_submission_method.data or None
    if not self.has_vat.data and (cat or method):
        self.has_vat.errors.append(
            "VAT category and submission method must both be empty when VAT is not registered."
        )
        return False
    if (cat is None) != (method is None):
        target = self.vat_submission_method if cat else self.vat_category
        target.errors.append(
            "VAT category and submission method must both be set or both be empty."
        )
        return False

    return True
```

**Route handler additions** — `create_client` and `edit_client` both gain the same lines:

```python
# inside create_client (and edit_client mirrored):
client = Client(
    # ... existing kwargs ...
    vat_category=(
        VatCategory[form.vat_category.data] if form.vat_category.data else None
    ),
    vat_submission_method=(
        VatSubmissionMethod[form.vat_submission_method.data]
        if form.vat_submission_method.data
        else None
    ),
)
```

For `edit_client`, also pre-populate the SelectFields on `GET`:

```python
if request.method == "GET":
    form.entity_type.data = client.entity_type.name
    form.vat_category.data = client.vat_category.name if client.vat_category else ""
    form.vat_submission_method.data = (
        client.vat_submission_method.name if client.vat_submission_method else ""
    )
```

**Tests for the cross-cutting block (`tests/test_clients_routes.py` — new file):**

- `POST /clients/new` with `has_vat=True, vat_category=A, vat_submission_method=EFILING` → 302; client persisted with `vat_category is VatCategory.A` and `vat_submission_method is VatSubmissionMethod.EFILING`.
- `POST /clients/new` with `has_vat=False, vat_category=A` → renders the form with an error on `has_vat`; no client persisted.
- `POST /clients/new` with `has_vat=True, vat_category=A`, method left blank → renders form with an error on `vat_submission_method`; no client persisted.
- `POST /clients/new` with `has_vat=True, vat_submission_method=MANUAL`, category left blank → renders form with an error on `vat_category`.
- `POST /clients/new` with `has_vat=True` and both VAT fields blank → succeeds (the "newly registered, details pending" case from 3a §a invariant 2).
- `POST /clients/<id>/edit` updates an existing client's VAT fields; `GET` pre-populates the SelectFields with the persisted enum's `name`.

### Out of scope for Ticket 3b (deferred to 3c+)

- **`notes` column on `ObligationInstance`.** Adding a column without an edit UI is half a feature; the schema add, the edit UI, and any read surface land together in 3c.
- **Transition metadata.** No `submitted_at`, `confirmation_number`, `payment_reference`, or `notes` parameters on the transition functions.
- **Regenerate-with-preservation service.** Changing a client's `vat_submission_method` mid-year does NOT recompute due dates on existing `PENDING` rows in 3b. That service is Ticket 3c.
- **Bulk transitions and bulk reassign.** Single-instance only in 3b.
- **Filter dimensions in the dashboard:** by client, by obligation_type, custom date range with date pickers, calendar/iCal export, multi-status selection.
- **Per-obligation detail page** (deep-link, edit notes, edit other fields).
- **Card-on-narrow-viewport** dashboard refactor.
- **Email notify-assignee wiring.** Stub button OK in a later iteration; SMTP plumbing is later.
- **User accounts / authentication.** Staff ≠ User. Login is a later ticket.
- **Cat E VAT201 generation.** Still raises `NotImplementedError("Category E pending domain confirmation")`.
- **VAT category turnover validation** (Cat C is mandatory > R30m) and `vat_number` requiredness when `has_vat=True`. Domain-rule checks for a later ticket.

### Decisions locked in for Ticket 3b (per Daniel)

1. **State-graph guardianship.** `app/services/obligations/transitions.py` is the SOLE documented happy path for status changes. No DB `CHECK` constraint, no `before_update` listener — direct ORM writes remain the admin-override escape hatch for SARS retroactive cancellations.
2. **Transitions API shape.** Three free module-level functions — `mark_submitted(instance)`, `mark_paid(instance)`, `mark_exempt(instance)` — that mutate in place and `raise ValueError` on illegal prior state. Single-instance only; no bulk variant. State-only — no transition metadata.
3. **OVERDUE is read-time only.** Two service functions in `app/services/obligations/predicates.py`: `is_overdue(instance, today) -> bool` and `overdue_filter(today) -> ColumnElement[bool]`. No `hybrid_property`. `today` is always a required parameter.
4. **`today_sast()` lives in `app/utils/dates.py`,** using stdlib `zoneinfo.ZoneInfo("Africa/Johannesburg")`. No pytz. The wrapper exists so no other module imports `zoneinfo` directly.
5. **Staff model fields.** `id`, `code` (unique, varchar 16), `full_name`, `email` (nullable), `role` (Enum `StaffRole` with values `TAX`, `SECRETARIAL`, `BOTH`), `active` (Boolean, default True), `created_at` (UTC tz-aware, `server_default=func.now()`). `code` and `full_name` are validated non-blank at construction via `@validates`.
6. **Staff vs User: separate concerns.** 3b ships Staff only — no login, no auth, no User model.
7. **`assignee_id` on `ObligationInstance`.** Nullable Integer FK → `staff.id`, `ON DELETE SET NULL`, indexed. Unassigned rows are first-class; the dashboard surfaces them as a filter category.
8. **SQLite FK enforcement in tests.** `tests/conftest.py` gains a `connect`-event listener that issues `PRAGMA foreign_keys = ON` on the test SQLite engine so the SET NULL behaviour is exercised at runtime, not only via schema introspection.
9. **Dashboard scope.** One page at `/dashboard/`. Three AND-combined filters: **Status** (stored values only), **Assignee** (active staff + "Unassigned"), **View** (`All` / `Due this week` / `Due next 30 days` / `Overdue`). Sort `submission_due_date ASC, client.legal_name ASC`. No pagination.
10. **Per-row actions** are inline `<button>`s inside per-action `<form method="post">`s, not dropdown menus. Reassign opens a single shared Bootstrap 5 modal at the bottom of the page, populated via ~10 lines of vanilla JS. OVERDUE shows as an inline red badge on the row's status column, not as a button.
11. **Filter-state preservation across actions.** Every POST handler `redirect`s with `**request.args`.
12. **`notes` deferred entirely.** No schema change in 3b. The column lands with its UI in 3c.
13. **VAT fields on the client form are in-scope.** `vat_category` and `vat_submission_method` are added as `SelectField`s on `ClientForm` with form-layer pairing validation mirroring the model invariants. Display shows "eFiling" / "Manual"; storage stays uppercase per the 3a decision. `EntityType[name]`-style name lookup applies in the route.
14. **Build order inside 3b.** B2 → B1 → B3 → Cross-cutting → B4. Each prior chunk has integration value at its merge point; B4 is the user-visible tie-together at the end.

---

## Ticket 3c — Regenerate-with-preservation + per-obligation detail page

**Scope discipline.** 3c does two things and stops. C1 upgrades the quick-win (`generate_and_persist`) shipped in `c81e0ad` into the **regenerate-with-preservation** service promised in 3a §(b). C2 adds the `notes` column to `ObligationInstance` together with the per-obligation detail page that lets a user read and edit it. Everything else 3b deferred — transition metadata, dashboard filter polish, bulk operations, calendar export, mobile card layout, email, auth, Cat E, turnover rules — stays deferred to 3d / 3e and beyond.

**Builds directly on 3b.** No 3b invariant is loosened. The transitions service (`mark_submitted` / `mark_paid` / `mark_exempt`) is unchanged. The state graph remains service-layer-only. `OVERDUE` is still read-time only. The only model schema addition in 3c is one nullable `notes Text` column on `obligation_instances` (C2). Build order: **C1 → C2.**

### C1) Regenerate-with-preservation — replace `app/services/obligations/regenerate.py`

The quick-win in `c81e0ad` only **adds** new periods. The full service handles three categories on every call:

| Category | Condition | Action |
|---|---|---|
| **Add** | Generated period whose `(obligation_type, period_end)` is not in DB for this client | `session.add()` the new instance — same as the quick-win. |
| **Refresh** | Existing `PENDING` row whose `(obligation_type, period_end)` matches a generated period | Recompute `submission_due_date` and `payment_due_date` against current client config. Update in place. |
| **Prune** | Existing `PENDING` row whose `(obligation_type, period_end)` does NOT match any generated period (e.g. Cat C → Cat A; or `has_vat` flipped True → False) | `session.delete()` the row. |

Rows in status `SUBMITTED`, `PAID`, or `EXEMPT` are **never** touched — neither refreshed nor pruned. This holds even when `has_vat` flips to False: terminal-state rows preserve history; only `PENDING` rows are deleted.

**Service signature:**

```python
from typing import NamedTuple


class RegenerateResult(NamedTuple):
    added: int
    updated: int
    deleted: int


def regenerate(client: Client, today: date | None = None) -> RegenerateResult:
    """Synchronise this client's obligation_instances with current config.

    Adds new periods, refreshes due dates on PENDING rows whose periods are still
    valid, and deletes PENDING rows whose periods are no longer generated.
    SUBMITTED, PAID, EXEMPT rows are never touched.

    Caller owns the commit.
    """
```

The `today` parameter mirrors `generate_vat201(today=...)` — exists for test determinism.

**Implementation skeleton in prose:**

1. Read all existing rows for this client into a `dict[(ObligationType, date), ObligationInstance]` keyed by `(obligation_type, period_end)`. Eager load so the row mutations below don't trigger re-queries.
2. Call `generate_vat201(client, today=today)` — the canonical set of currently-due instances. The generator's pre-conditions already return `[]` when `has_vat` / category / method aren't all set.
3. Index the generated list by the same key.
4. Walk both keysets together:
   - **In generated, not in existing** → `session.add()`, increment `added`.
   - **In both** → if existing `status is PENDING` and either due date differs, copy the new dates onto the existing row and increment `updated`. If status is terminal, skip.
   - **In existing, not in generated** → if existing `status is PENDING`, `session.delete(row)` and increment `deleted`. If status is terminal, leave untouched.
5. Return `RegenerateResult(added, updated, deleted)`.

Dict-based one-pass rather than two SQL queries because the dataset is small (≤ 24 VAT201 rows per client at the 12-month window) and per-row decisions need both Python-side state checks and date comparisons.

**Route change — `app/clients/routes.py::regenerate_obligations`:**

Replace `generate_and_persist(client)` with `regenerate(client)`. Flash message becomes:

```
Regenerated obligations for {legal_name}: added 3, updated 12, removed 0.
```

No zero-suppression — uniform three-count message is easier to skim.

**Template helper text — `app/templates/clients/form.html`:**

Replace the existing one-line description below the "Regenerate obligations" button with:

> Refreshes pending VAT201 instances to use the current submission method, adds any new periods, and removes pending periods that no longer apply. Submitted, paid, and exempt instances are never changed.

**Files modified/created in C1:**

- `app/services/obligations/regenerate.py` — replace `generate_and_persist` with `regenerate` + `RegenerateResult`. The old function has no other callers; delete it cleanly rather than keep a shim.
- `app/clients/routes.py` — call `regenerate`; richer flash message.
- `app/templates/clients/form.html` — update helper text.
- `tests/services/obligations/test_regenerate.py` — new test module (see below).
- `tests/test_clients_routes.py` — update existing regenerate-route tests for the new flash text and counts.

**Tests for C1 (`tests/services/obligations/test_regenerate.py`):**

Each test seeds a client + a fixed `today` then asserts the `RegenerateResult` and the DB state.

- **First run on a new client** (Cat C, EFILING) — `added == 12`, `updated == 0`, `deleted == 0`.
- **Second run with unchanged config** — `RegenerateResult(0, 0, 0)`. Row PKs unchanged (no churn).
- **Refresh case** — client starts EFILING; regenerate; switch to MANUAL; regenerate again. Assert `updated > 0`, all `PENDING` rows now use MANUAL due dates, row PKs unchanged.
- **Prune case — category change** — Cat C → Cat A. Periods ending in even months are no longer generated. Assert `deleted > 0`; the surviving `PENDING` rows all have `period_end.month in {1, 3, 5, 7, 9, 11}`.
- **Prune case — `has_vat` off-ramp** — Cat C client with one `PENDING` (Dec), one `SUBMITTED` (Nov), one `PAID` (Oct), one `EXEMPT` (Sep). Set `has_vat=False`. Regenerate. Assert `RegenerateResult(0, 0, 1)`; the `PENDING` row is gone, the other three remain unchanged.
- **Terminal-state immutability** — seed a `SUBMITTED` row with a deliberately wrong `submission_due_date`. Regenerate. Assert the row's `submission_due_date` is unchanged.
- **Mixed call** — switch method AND category between two regenerate calls; assert all three counts are non-zero and the final state matches what `generate_vat201` would now produce for the `PENDING` slice.

### C2) `notes` column + per-obligation detail page

**Schema.** Add one column to `obligation_instances`:

| Column | Type | Nullable | Default | Reason |
|---|---|---|---|---|
| `notes` | `Text` | Yes | — | Free-form, optional. `Text` not `String(N)` — no business reason to cap at the DB level. Soft cap in form validation (4000 chars). |

**Migration:** single autogenerated Alembic revision adds `obligation_instances.notes`. Existing rows are backfilled `NULL`.

**Model change — `app/models/obligation.py`:**

```python
notes: Mapped[str | None] = mapped_column(Text, nullable=True)
```

Import `Text` from `sqlalchemy` — one-line addition to the existing import block.

**Detail page — `app/dashboard/routes.py`:**

Two new routes:

```python
@bp.get("/obligations/<int:obligation_id>")
def obligation_detail(obligation_id: int): ...


@bp.post("/obligations/<int:obligation_id>/notes")
def update_obligation_notes(obligation_id: int): ...
```

The GET renders `dashboard/detail.html` with the full obligation, client, assignee, the `generated_at` / `updated_at` timestamps, the derived `is_overdue(instance, today_sast())` badge, the same action buttons as the list (mark-submitted / mark-paid / mark-exempt / reassign), and a notes textarea form.

The POST handler updates `instance.notes` (treating empty / whitespace-only as `None`), commits, flashes success, redirects to `obligation_detail`.

**Action buttons on the detail page redirect back to the detail page, not the list.** Implementation: each action `<form>` on the detail template includes a hidden `<input name="next" value="detail">`. The existing list-route action handlers (`mark_obligation_submitted`, `mark_obligation_paid`, `mark_obligation_exempt`, `reassign_obligation`) gain one branch:

```python
if request.form.get("next") == "detail":
    return redirect(url_for("dashboard.obligation_detail", obligation_id=instance.id))
return _redirect_to_list_preserving_filters()
```

No new POST endpoints; the existing five serve both pages.

**Form — `app/dashboard/forms.py`:**

```python
class NotesForm(FlaskForm):
    notes = TextAreaField(
        "Notes",
        validators=[validators.Optional(), validators.Length(max=4000)],
    )
    submit = SubmitField("Save notes")
```

4000-char soft cap — generous (well over a screen of prose) and stops accidental megabyte pastes. Adjustable later without migration.

**List-view indicator — `app/templates/dashboard/list.html`:**

Wrap the obligation-ID cell in a link to the detail page:

```jinja
<a href="{{ url_for('dashboard.obligation_detail', obligation_id=inst.id) }}">{{ inst.id }}</a>
```

Add a small note icon next to the ID when `inst.notes` is non-empty:

```jinja
{% if inst.notes and inst.notes.strip() %}
  <span title="Has notes" aria-label="Has notes">📝</span>
{% endif %}
```

Unicode 📝 rather than pulling in Bootstrap-icons for a single glyph. This is the only emoji that ships in the codebase — it's an affordance, not decoration.

**Files modified/created in C2:**

- `app/models/obligation.py` — add the `notes` column.
- `migrations/versions/<rev>_add_notes_to_obligation_instances.py` — autogenerated single-column add.
- `app/dashboard/routes.py` — two new routes + the `next=detail` branch in the four existing action handlers.
- `app/dashboard/forms.py` — `NotesForm`.
- `app/templates/dashboard/detail.html` — new template.
- `app/templates/dashboard/list.html` — obligation-ID link + notes indicator.
- `tests/test_obligation_model.py` — `notes` defaults to `None`, persists arbitrary text, accepts `None` explicitly.
- `tests/dashboard/test_routes.py` — extend with the detail-page tests below.

**Tests for C2 (additions to `tests/dashboard/test_routes.py`):**

- `GET /dashboard/obligations/<id>` renders 200 with the obligation's status, due date, client name, and notes textarea pre-populated from the DB.
- `GET /dashboard/obligations/<id>` for a non-existent ID returns 404.
- `POST /dashboard/obligations/<id>/notes` with non-empty text persists, redirects to the detail page, success flash.
- `POST /dashboard/obligations/<id>/notes` with empty / whitespace text persists `None`.
- `POST /dashboard/obligations/<id>/notes` with > 4000 chars rejects (form-validation error, no DB write).
- CSRF: POST without token returns 400.
- **`next=detail` round-trip** — `POST .../mark-submitted` with form field `next=detail` redirects to `dashboard.obligation_detail`, not the list.
- **List page links to detail** — list HTML contains the `href` for each instance's detail URL.
- **Notes indicator** — list HTML contains the indicator span only for rows whose `notes` is non-empty.

### Out of scope for Ticket 3c

Two follow-ups are reserved as named tickets so the slots are committed, not vague:

- **Ticket 3d (reserved): Transition metadata** — `submitted_at`, `paid_at`, `exempted_at`, plus optional `confirmation_number` and `payment_reference` captured on the dashboard action forms and wired into the three transition functions.
- **Ticket 3e (reserved): Dashboard filter polish** — by client, by obligation_type, multi-status, custom date range.

Items below have no reserved slot yet — they wait until concrete demand surfaces:

- Calendar / iCal export.
- Bulk transitions and bulk reassign.
- Mobile card-layout fallback.
- Email notify-assignee (SMTP plumbing).
- User accounts / authentication.
- Cat E VAT201 generation.
- VAT category turnover validation; `vat_number` required when `has_vat=True`.
- Date-override editing on the detail page (only `notes` is editable in 3c).
- Auditing of who changed what on regenerate (the `RegenerateResult` is a flash-message snapshot, not a stored audit log).

- **Ticket 3f (reserved): AFS preparation deadline tracking** — annual obligation per active client, due six months after financial year-end. Same model and dashboard surface; new `ObligationType.AFS` and generator.

- **Ticket 3g (reserved): Ad-hoc client task tracking** — non-statutory work items (letters, document requests, follow-ups) originating from reception or staff. Same dashboard surface as obligations; new `ObligationType.TASK` with null-allowed `period_start` / `period_end` and a user-provided due date. Origin: typed in, not generated.

### Decisions locked in for Ticket 3c (per Daniel)

1. **Three categories on every regenerate call:** add, refresh, prune. Terminal-state rows are never touched.
2. **Stale `PENDING` rows are hard-deleted.** No "auto-EXEMPT", no `is_stale` flag. Users wanting an audit trail must EXEMPT a row manually before changing client config.
3. **`has_vat` True → False symmetry:** all `PENDING` VAT201 rows for that client are deleted; SUBMITTED / PAID / EXEMPT rows preserve history.
4. **Return shape:** `RegenerateResult(added, updated, deleted)` `NamedTuple`. Uniform three-count flash message, no zero-suppression.
5. **`notes` is `Text`, nullable, no default.** Form-layer soft cap 4000 chars; no DB-level cap.
6. **Detail page in 3c edits notes only.** Status changes go through the existing transition buttons; reassignment through the existing modal replicated on the detail page. Dates are not editable.
7. **Action buttons exist on both list and detail pages,** served by the same five POST endpoints, via a `next=detail` form field that branches the post-success redirect.
8. **Notes indicator on the list is a small inline icon next to the obligation ID** when `notes` is non-empty and non-whitespace. No preview snippet, no separate column.
9. **Deferred work has explicit ticket slots:** Ticket 3d for transition metadata; Ticket 3e for dashboard filter polish. Items beyond 3e have no reserved slot until demand surfaces.
10. **Build order: C1 → C2.** Each chunk has integration value at its merge point.
