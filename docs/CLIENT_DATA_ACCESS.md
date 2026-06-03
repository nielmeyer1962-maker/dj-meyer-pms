# Client Data Access — is the PMS import the best option?

The new requirement (3 June 2026): the firm is on **Claude Teams**, and staff will
reference the **client database** when they draft client letters and communication.
This document answers *"is importing into the PMS database the best option to have?"* —
because the answer is **"yes, but the import alone is not enough."**

## The hard constraint

- The PMS is **Flask + PostgreSQL on a local server** (`192.168.1.248`, `:5433`).
- **Claude Teams runs in the cloud and cannot reach that local database.** Uploading a
  spreadsheet into a chat is not a database; it goes stale the moment the data changes.
- **POPIA:** every seat on a shared Claude Project can read that Project's knowledge.
  Client ID numbers, tax refs and emails are sensitive — they cannot be poured into a
  shared Project without thought.

## Is "import into the PMS DB" still right?

**Yes — as the single source of truth.** The PMS gives you what a pile of spreadsheets
or Project documents never will: unique-key integrity and de-duplication, the
obligations/deadline engine, staff allocation, and one auditable record. Client master
data must **not** live only inside Claude Project documents — they have no integrity, no
obligations engine, and drift out of date immediately.

**But the import does not, by itself, let Claude Teams write letters.** For that you need
an *access layer* from the database to Claude Teams. So the real answer is:
**import into the PMS, AND add a Claude-facing way to read it.**

## Options for Claude Teams access

**Option 1 — Sanitised export to Project knowledge** *(do now; zero infra)*
A PMS script/route exports a clean **per-staff** client reference (name, entity type,
trading name, contact person, Main/CC email, phones, address, allocated staff, and any
obligations/returns due). Upload it to each staff member's Claude Project; refresh
weekly or on demand.
- ✅ Works today, no infrastructure, POPIA-manageable (scope per staff, omit raw IDs).
- ❌ Static — needs a refresh; not live.

**Option 2 — Read-only MCP connector** *(build next; the durable answer)*
A small read-only MCP server in front of the PMS DB; Claude Teams connects to it as a
connector. A staff member says *"draft a letter to <client>"* and Claude pulls the live
details, scoped to that staff member's allocated clients.
- ✅ Live, access-controlled, queryable, no bulk export of sensitive data.
- ❌ Needs infra (must be reachable from Claude's cloud — host it or tunnel it), auth, and
  a security review. Interactive-auth MCP servers may not work in headless/cron runs.

**Option 3 — Generate letters inside the PMS**
The PMS already holds the data *and* the letterhead spec. Claude Teams drafts the body;
the PMS merges client details + letterhead server-side, so sensitive data never leaves
the server. Complements Options 1/2.

## Recommendation — hybrid, phased

1. **PMS Postgres stays the single source of truth.** Finish the import (Tickets A/B done;
   use the richer contact list below).
2. **Phase 1 (now): sanitised per-staff export → each staff member's Claude Project.**
   Letter-writing works immediately and POPIA-safely.
3. **Phase 2 (next): read-only MCP connector** for live, allocation-scoped access — matches
   the "future integrations" already noted in `CLAUDE.md`.
4. **Raw ID / tax numbers stay server-side**, surfaced only at the moment a specific letter
   needs them — never sitting in shared Project knowledge.

### POPIA guardrails (apply to Phase 1 and 2)

- **Per-staff scoping** — a staff member's Project / connector view carries only their
  allocated clients.
- **Sanitised reference** — no ID/tax numbers in shared Project knowledge.
- **Pull identifiers per-letter** from the secure DB when a specific document needs them.

## Import-quality improvements (found in the data)

- **Use the "Customer Contact List (Dewald)" format as the contact source**, not the old
  QuickBooks export. It has **Main Email, CC Email**, structured address (**Street1,
  Street2, City, Postcode**), Work/Mobile phone, and **clean Rep codes (`CANDI`)** that
  match the staff seed. The QB export has no email and messy Reps (`Quinlyn`, `CHANT`).
- **Coverage gap:** only Candice's ~163 clients exist in this clean format so far. Get the
  same export for all 8 staff, or one consolidated file, before the contact merge.
- **Refine Ticket B:** the single `email` / `physical_address` / `postal_address` columns
  don't capture `CC Email`, `Work Phone`, or a *structured* address. For letter-quality
  addresses, consider structured columns (`street1`, `street2`, `city`, `postcode`) plus
  `cc_email`. **Decision pending** — see open questions.
- **Matching key for the merge:** registration number (companies) / income tax ref
  (individuals); fall back to name using the reconciliation workbook's match-confidence.
- **IT14 / IT12 files map directly to Ticket D** (return tracking): `Year of Assessment`,
  `Version`, `Status Category`, `Filing Date`, `Amount Due (R)`, `Source Status (verbatim)`.
  Clean and ready — see DATA_SOURCES.md.

## New open questions (added to the SCHEMA_PLAN list)

6. Letter-writing access: **Phase 1 export now**, or jump straight to the **MCP connector**?
7. Ticket B address: keep simple Text, or **structured** (`street1/2`, `city`, `postcode`)
   + `cc_email` to support proper letter addressing?
8. Will Dewalt produce the **clean contact export for all 8 staff** (not just Candice)?
