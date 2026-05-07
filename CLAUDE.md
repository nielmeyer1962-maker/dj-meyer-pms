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

**Staff:**

- Candice, Jeanne Marie, Niel, Quinlyn, Caroline, Stacey — Accounting and Tax
- Tsego — Secretarial (handles all CIPC annual returns for Pty Ltd and CC entities)

**Assignment rules to encode:**

- Every Pty Ltd and CC client is also assigned to Tsego for the CIPC annual return obligation, regardless of who else is on the engagement.
- Tax obligations follow the staff member assigned to that client's tax engagement.

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

**Not yet chosen.** On first session, recommend a stack to Daniel based on:

- Daniel has prior Flask / Python experience and built a small accounting web app before.
- Single firm, around ten staff, low concurrent users.
- Will likely run on a small VPS or local server in South Africa.
- Must be maintainable by one person (Daniel) with AI assistance.
- Will later integrate with the Zoho Projects API, Gmail / SMTP, and n8n webhooks.

Default to boring, well-supported choices. Justify the recommendation in five to ten lines and wait for sign-off before scaffolding anything.

## Coding conventions (apply once the stack is chosen)

- Prefer clarity over cleverness. Daniel will be reading this code in six months.
- Type hints everywhere if Python is chosen.
- One concept per file. Small modules.
- Store all timestamps as UTC, display in `Africa/Johannesburg`. Always be explicit about which.
- All money values as integers in cents, or `Decimal`. Never floats.
- Database migrations are first-class. No schema changes without a migration.
- Tests are required for any logic that calculates a deadline or assigns work. Pure UI may skip tests for now.
- Commit early and often, with messages that describe *why*, not *what*.

## Working agreement

- Before starting a new feature, restate the goal in one sentence and list the files you intend to create or change. Wait for "go" before editing.
- After completing a task, summarise what changed and what is still pending. No silent scope expansion.
- If a SARS rule, statutory deadline, or piece of legislation matters for the logic, flag it and ask Daniel to confirm — do not guess from training data.
- Ask before introducing a new dependency. Justify it in one line.
