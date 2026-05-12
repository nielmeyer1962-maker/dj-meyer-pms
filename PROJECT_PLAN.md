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
