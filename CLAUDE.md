# DJ Meyer Practice Management System

This file orients Claude Code to the project. Read it at the start of every session.

## What this is

An internal practice management system for **DJ Meyer & Co**, a South African professional accounting, tax, and advisory firm based in Gauteng. The system manages the *firm's work* — which client owes what statutory obligation, when it is due, who is responsible, and what the status is.

## What this is NOT (do not scope-creep into these)

- Not a bookkeeping or general ledger system. Sage, CaseWare, and QuickBooks handle that.
- Not a document management system. (May add later.)
- Not a CRM. Zoho handles that.
- Not a time-and-billing system. (May add later.)
- Not multi-tenant SaaS. One firm, single instance.

If a new requirement seems to drift toward any of the above, stop and confirm with Daniel before implementing.

## The firm

**Practice areas:** SA tax compliance and dispute resolution, B-BBEE compliance, corporate and estate law documentation, business valuations, secretarial work.

### People and roles

| Code | Name | Email | Dept / role | Notes |
|------|------|-------|-------------|-------|
| NIEL | Niel Meyer (Daniel Jacobus Meyer) | niel@djmeyer.co.za | Tax & Accounting — **Principal / owner** | Involved in everything except secretarial. SAIPA No. 03393. |
| JEANNE | Jeanne-Marie Meyer | jeanne-marie@djmeyer.co.za | Tax & Accounting — **Assistant Principal** | Niel's daughter; successor / future owner. SAIPA No. 62098. |
| CANDI | Candice van der Merwe | candice@djmeyer.co.za *(TBC)* | Tax & Accounting | |
| STACY | Stacy Roux | stacy@djmeyer.co.za | Tax & Accounting (tax) | Married to Dewald. |
| QUINLYN | Quinlyn Breedske | quinlyn@djmeyer.co.za | Tax & Accounting | |
| CAROLINE | Caroline Lombard | caroline@djmeyer.co.za | Tax & Accounting | |
| DEWALD | Dewald Roux | dewald@djmeyer.co.za *(TBC)* | Tax & Accounting (back office) | Stacy's husband. Supports Candice & Stacy; converts source data to Excel for import into **CaseWare** (where final AFS are prepared). Not client-allocated. |
| TSEGO | Tsego Mogale | tsego@djmeyer.co.za | Secretarial (runs the dept) | CIPC compliance, Beneficial Ownership, **Workmen's Compensation (COIDA)**, and SARS registrations. |

`StaffRole` enum mapping: Tax & Accounting → `TAX`, Secretarial → `SECRETARIAL`.
`BOTH` is reserved for anyone working across both departments — nobody currently.
The firm is **SAIPA-registered, Practice No. 03393**, at 6 Eleventh Avenue, Northmead, Benoni 1500.

### How the work is divided

**Tax & Accounting team** (Niel, Jeanne Marie, Candice, Stacy, Quinlyn, Caroline):

- Each client is **allocated to one** tax/accounting staff member who owns all of that
  client's work.
- Recurring returns: **VAT201** (monthly or bi-monthly), **EMP201** (monthly),
  **EMP501** (bi-annual).
- Annual: prepare **Annual Financial Statements** (finalised in **CaseWare**), submit the
  **ITR14** (company income tax), and submit **ITR12** (individual income tax) for the
  company's members/owners.
- Handle all **SARS queries and requests** for their allocated clients.
- **Back office (Dewald Roux)** supports Candice & Stacy — converts source data to Excel
  for import into **CaseWare**, where the final Annual Financial Statements are prepared.
  Not allocated clients of his own.

**Secretarial (Tsego):**

- **CIPC** compliance — annual returns for every Pty Ltd and CC, plus **Beneficial
  Ownership** filings.
- **SARS registrations** — registering new VAT numbers, Income Tax numbers, and
  Employees' Tax (PAYE) numbers.

### Assignment rules to encode

- Every Pty Ltd and CC client is also assigned to **Tsego** for the CIPC annual return
  (and Beneficial Ownership), regardless of who else is on the engagement.
- All other obligations follow the **single tax/accounting staff member** the client is
  allocated to.

### Known future requirement — SARS correspondence inbox (not yet built, do not build unprompted)

SARS queries/requests arrive two ways today: as **messages on Niel's cell phone**, and in
**eFiling under "SARS Correspondence."** A future phase must let staff **import that
correspondence into dj-meyer-pms** and attach it to the relevant client/obligation so
nothing is missed. Captured here so it isn't lost — build only as an approved ticket.

## Domain vocabulary (SA-specific)

- **SARS** — South African Revenue Service
- **CIPC** — Companies and Intellectual Property Commission
- **ITR12** — individual income tax return
- **ITR14** — company income tax return
- **IRP6** — provisional tax return
- **VAT201** — VAT return
- **EMP201** — monthly PAYE / UIF / SDL return
- **EMP501** — bi-annual employer reconciliation
- **DTR02** — dividends tax return
- **B-BBEE** — Broad-Based Black Economic Empowerment (annual certificate or sworn affidavit)
- **TAA** — Tax Administration Act (28 of 2011)
- **ITA** — Income Tax Act (58 of 1962)
- **AFS** — Annual Financial Statements

Entity types in scope: Individual, Sole Proprietor, Pty Ltd, CC, Trust, Partnership, NPC.

## Stack

Chosen and in use (boring, well-supported, maintainable by one person + AI):

- **Language:** Python 3.12+ (note: the local `.venv` currently runs 3.13 — see "Known issues").
- **Web:** Flask 3 (app-factory pattern, blueprints).
- **ORM:** SQLAlchemy 2.0 with typed `Mapped[...]` models; Flask-SQLAlchemy.
- **Migrations:** Flask-Migrate / Alembic. No schema change without a migration.
- **Forms / CSRF:** Flask-WTF + WTForms. CSRF protection is global (`csrf.init_app`).
- **Database:** PostgreSQL (psycopg2-binary). Local dev DB runs on `localhost:5433`.
- **Templating:** Jinja2 server-rendered HTML; `app/templates/base.html` is the shell.
- **SA calendar logic:** `holidays` + `tzdata` for business-day / due-date maths.
- **Mail (future):** Flask-Mail (Gmail SMTP) — configured but not yet wired into features.
- **Tooling:** `ruff` (lint + format, line-length 100, target py312), `pytest` (+ pytest-flask).

Planned future integrations (not built yet): Zoho Projects API, Gmail / SMTP notifications, n8n webhooks.

## Architecture

Layered, with business logic kept out of the routes:

```
run.py                  Entry point: load_dotenv() → create_app() → app.run(debug=True)
seed.py                 Dev helper: inserts 3 starter Staff rows.
app/
  __init__.py           create_app() factory — registers extensions + blueprints.
  config.py             Config class, reads env vars (SECRET_KEY, DATABASE_URL, MAIL_*).
  extensions.py         Singletons: db (SQLAlchemy), migrate, csrf.
  models/               Data layer — typed SQLAlchemy models + invariants.
    client.py             Client, EntityType (incl. INC), VatCategory, VatSubmissionMethod.
    obligation.py         ObligationInstance, ObligationType (VAT201/EMP201/ITR14),
                          ObligationStatus (PENDING/IN_PROGRESS/SUBMITTED/PAID/EXEMPT).
    cipc.py               CIPCAnnualInstance, CIPCAnnualStatus (7-state AR/BO machine).
    task.py               Task, TaskStatus (ad-hoc client tasks).
    staff.py              Staff, StaffRole (TAX / SECRETARIAL / BOTH).
  services/             Business logic — NO Flask, pure functions, fully unit-tested.
    obligations/          predicates (overdue), transitions (state graph),
                          vat201 / emp201 / itr14 (period/due-date generation), regenerate.
    cipc/                 due_dates, fees, generate, predicates, regenerate, transitions.
    tasks/                predicates.
  <blueprint>/          Presentation layer — one folder per feature area:
    clients/              routes + forms     → URL prefix /clients
    dashboard/            routes + forms     → URL prefix /dashboard  (obligations)
    tasks/                routes + forms     → URL prefix /dashboard/tasks
  templates/            Jinja2 templates, grouped per blueprint.
  utils/                dates (today_sast), business_days, staff helpers.
migrations/             Alembic migration history (18 revisions; latest adds ITR14 +
                        CIPC AR fee tables).
tests/                  pytest suite mirroring the app tree (319 test functions).
```

**Key design rules already established in the code (follow them):**

- **Status is a stored enum; "OVERDUE" is derived at read time** (status PENDING/OPEN AND
  due date < today in `Africa/Johannesburg`) — never a stored value.
- **State transitions live only in the service layer** (`services/obligations/transitions.py`),
  never in models or routes. Routes call the service, catch `ValueError`, flash, redirect.
- **Cross-field invariants** (VAT pairing, year-end pairing) are enforced via SQLAlchemy
  `@validates` + `before_insert`/`before_update` events on the model.
- **Clients/Staff are soft-deleted** (`active=False`), not hard-deleted. FKs use
  `ON DELETE RESTRICT` (obligations/tasks → client) and `SET NULL` (→ staff assignee).
- **Avoid N+1:** `selectinload` the `client` and `assignee` relationships on list views.

## How to run

All commands from the project root, using the project venv (`.venv\Scripts\`).

```powershell
# 1. Activate the virtual environment (Windows PowerShell)
.\.venv\Scripts\Activate.ps1

# 2. Install / update dependencies (first run, or after a pull)
pip install -r requirements.txt -r requirements-dev.txt

# 3. Configure environment (first run only)
copy .env.example .env
#    then edit .env: set DATABASE_URL (Postgres on :5433), SECRET_KEY, MAIL_* if needed

# 4. Apply database migrations
flask --app run db upgrade

# 5. (optional) Seed starter staff rows
python seed.py

# 6. Run the dev server  → http://localhost:5000
python run.py
```

Quality gates (run before every commit):

```powershell
ruff check .        # lint  — must be clean
ruff format .       # auto-format
pytest -q           # full suite — must be green
```

Production (per README): `gunicorn -w 4 "run:app"` behind nginx, `DEBUG=False`, strong `SECRET_KEY`.

## Current state (update as it changes)

*Last reconciled 2026-06-17 against `main` @ `18b161e`. See `PROJECT_PLAN.md` →
"Delivery status" for the per-ticket ledger.*

- Branch `main`, tracking `origin/main` (GitHub: nielmeyer1962-maker/dj-meyer-pms).
- **Built so far:** Client model + CRUD (incl. allocation, CIPC anniversary, and
  structured contact fields), Staff model, ad-hoc **Tasks** CRUD (Ticket 3g), and a
  unified deadline **dashboard** (filters: status / assignee / view / type / client;
  per-row submit/in-progress/paid/exempt/reassign/notes), rendered through the pure
  `DashboardItem` adapter that unifies obligations and CIPC rows.
- **Obligation generators:** VAT201, EMP201 (Ticket 4e), ITR14 (Ticket 4a).
  `ObligationStatus` is `PENDING → IN_PROGRESS → SUBMITTED → PAID` with `EXEMPT` off-ramp.
- **CIPC Annual Return** (Ticket 4g) is a *separate* subsystem — `CIPCAnnualInstance`
  with its own 7-state machine (`GENERATED → INVOICED → INVOICE_PAID → BO_SUBMITTED →
  AR_SUBMITTED → CLOSED`, plus `DECLINED`), BO-before-AR ordering, and an entity-aware
  fee reference table.
- **Not yet built:** transition metadata (3d), AFS tracking (3f), multi-status / custom
  date-range dashboard filters. ON_HOLD status remains deferred.
- **Working tree:** clean of code changes (only untracked local data files present).

## Known issues / cleanup backlog

- **Python version drift:** `.venv` runs 3.13 but `pyproject.toml` / ruff target 3.12.
  Either align the venv to 3.12 or bump the target deliberately.
- **`gunicorn` is referenced in README deploy but not in `requirements.txt`** — add it.
- **`config.py` default `DATABASE_URL`** (`postgresql://localhost/djmeyer_pms`, no port)
  is stale vs. the real `:5433` DB. Harmless while `.env` is present; fix the default.

## Coding conventions

- Prefer clarity over cleverness. Daniel will be reading this code in six months.
- Type hints everywhere (Python). Typed `Mapped[...]` columns on all models.
- One concept per file. Small modules. Keep business logic in `services/`, not routes.
- Store all timestamps as UTC (`DateTime(timezone=True)`), display in `Africa/Johannesburg`.
  Always be explicit about which.
- All money values as integers in cents, or `Decimal`. Never floats.
- Database migrations are first-class. No schema changes without a migration.
- Tests are required for any logic that calculates a deadline or assigns work. Pure UI may
  skip tests for now. The test tree mirrors the app tree.
- Commit early and often, with messages that describe *why*, not *what*.

## Working agreement

- Before starting a new feature, restate the goal in one sentence and list the files you intend to create or change. Wait for "go" before editing.
- After completing a task, summarise what changed and what is still pending. No silent scope expansion.
- If a SARS rule, statutory deadline, or piece of legislation matters for the logic, flag it and ask Daniel to confirm — do not guess from training data.
- Ask before introducing a new dependency. Justify it in one line.
