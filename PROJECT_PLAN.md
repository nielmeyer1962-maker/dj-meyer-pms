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
