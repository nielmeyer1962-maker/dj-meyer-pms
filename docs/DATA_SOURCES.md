# Data Sources & Import Plan

Working reference for getting the firm's real client data into dj-meyer-pms.
Captured 3 June 2026 from the reconciliation files Dewalt is preparing. Update as
the source files and the schema evolve. **No raw ID numbers / tax refs in this file**
(POPIA — keep those in the database, not in committed docs).

## Where the source files live

`Y:\DJ MEYER & CO\` on `\\192.168.1.248\Datastore` (Y: drive). Many working copies
exist; the authoritative ones at time of writing are listed below.

## 1. Master reconciliation workbook (primary)

**`Master_Client_List_Populated_01062026_IT12_v4.xlsx`** — 15 sheets. The ones that
feed the PMS:

| Sheet | ~Rows | Becomes | Key columns |
|-------|------|---------|-------------|
| **Master Client List** | 640 | Companies / CCs register | `Company (per Tsego)`, `Reg Number`, `ID Number`, `Director/Owner`, `CIPC Month`, `Due Day`, `Staff Member`, `SARS Tax Ref` (+ duplicate/match-confidence flags) |
| **It 12 return** | 260 | Individuals + IT12 return tracking | `Surname`, `Initials`, `Income Tax Ref`, `Year`, `Version`, `Return Type`, `SARS Status`, `Filing Date` |
| **Trusts** | 44 | Trust clients | names only (thin) |
| **Beneficial Owner Groups** | 73 | Owner → entity groups | `Beneficial Owner`, `# of Entities`, `ID Number`, `Companies`, `Staff Member(s)` |
| **Aerocom Group** | 17 | Group/entity test case (Niel's own group, NOT a client) | `Entity`, `Reg Number`, `CIPC Month`, `Due Day`, `Staff` |
| **Staff Allocation** | 8 | Per-staff workload by CIPC month | `Staff Member`, `Total Entities`, Jan–Dec counts |

Working/QA sheets (not imported): `Cover`, `Unmatched - Action Required` (71 rows),
`Folders not in Tsego List`, `efiling list`, `IT12 New/Estimates/Stats`, `Sheet10/11`.

## 2. Supplementary files

- **`Copy of Quickbooks contacts26May2026 Dewald.xlsx`** — original QuickBooks export
  (before Dewalt's Candice corrections). ~657 customers. **Headers on row 4**, data
  from row 5 (title block rows 1–3). Columns: `Active Status`, `Customer`, `Bill to`,
  `Primary Contact`, `Company`, `First Name`, `M.I.`, `Last Name`, `Main Phone`,
  `Mobile`, `Fax`, `Balance Total`, `VAT Registration Number`, **`Rep` (= staff member)**.
  ⚠️ No Email and no physical-address column in this export.
- **`Master Edit (Dewald) 2.xlsx`** — Dewalt's corrected list of **Candice's** clients.
  ~179 rows, 3 columns (no header): `#`, `Company`, `Reg Number`. A patch to allocations
  / reg numbers, not a standalone source.

## Field → `Client` model mapping

| Source column | `Client` field | Status |
|---|---|---|
| Company (per Tsego) / Customer | `legal_name` | ✅ exists |
| Reg Number | `registration_number` | ✅ exists |
| SARS Tax Ref / Income Tax Ref | `tax_ref` | ✅ exists |
| VAT Registration Number | `vat_number` | ✅ exists |
| (entity kind) | `entity_type` | ✅ exists (Pty Ltd / CC / Individual / Trust) |
| **Staff Member / Rep** | — | ❌ **no allocated-staff field** |
| **CIPC Month** | — | ❌ no CIPC anniversary month (≠ `year_end_month`) |
| **Due Day** | — | ❌ no CIPC due-day |
| **Director/Owner + ID** | — | ❌ no owner/director link |
| **Main Phone / Mobile / Fax / contact name** | — | ❌ no contact fields |
| Beneficial Owner Groups (whole sheet) | — | ❌ no group/owner model |

## Schema additions needed (design as tickets — not yet built)

1. **`Client.allocated_staff_id`** → owning tax/accountant (FK to `staff`, `SET NULL`).
2. **CIPC fields** on companies: anniversary month + due day → drives the CIPC annual-return obligation.
3. **Contact fields** (or a `Contact` table): phone, mobile, email, address, contact person.
4. **Beneficial Owner / Group model**: `BeneficialOwner` (= "Shareholder" under the
   General Laws Amendment Act 22 of 2022) linked many-to-many to entities. Aerocom Group
   is the test case. Accept 4 ID formats (SA ID, passport, company reg, redacted CIPC AR)
   — do not drop foreign nationals.
5. **IT12 individuals**: model the return as an obligation/return-instance (year, version,
   SARS status, filing date), like `ObligationInstance`.

## Data-quality caveats (read before importing)

- **Mid-sanitisation.** Source carries `Possible/Exact Duplicate`, `Match Confidence`,
  and a 71-row "Unmatched – Action Required" tab. Import into a **staging table** first,
  or wait for Dewalt's signed-off version. Do not import straight to production tables.
- **`Rep` normalisation.** QB `Rep` values mix first names and codes (e.g. `Quinlyn`,
  `CHANT`). Build a `Rep → Staff.code` lookup; flag unmatched reps for a manual pass.
- **Email/address gap.** The QB export lacks email + physical address. Confirm the source
  for those before promising a contact merge.
- **POPIA.** ID numbers and tax refs are sensitive. Keep them in the DB only; never in
  committed docs, portable Project knowledge, or chat.

## Recommended import order

1. Seed `staff` (done — `seed.py`).
2. Add schema (tickets above) + migrations + tests.
3. Stage-import companies (Master Client List) → review unmatched → promote.
4. Apply Candice patch (`Master Edit (Dewald) 2`).
5. Merge QB contact details (phone/mobile/fax/VAT/Rep) onto matched clients.
6. Import individuals (It 12 return) + IT12 return tracking.
7. Import trusts and beneficial-owner groups (Aerocom first, as the test).

## Three destinations for the firm knowledge (so it isn't poured into one place)

1. **This repo's `CLAUDE.md`** — firm/domain facts the code needs (staff, roles, CIPC rules). ✅
2. **The PMS database** — the actual records (this document's job).
3. **Claude Team account → Project knowledge** — document-generation knowledge from
   `07_Combined_All_in_One.md` (letterhead spec, house style, valuation methodology,
   bank-statement conversion standard, client-specific rules). NOT repo code or PMS data.

## Open questions for Niel

- Which file holds client **email + physical address** (not in the QB export seen)?
- Confirm the `Rep → Staff` mapping for non-obvious codes (e.g. `CHANT`).
- Owner role: keep Niel & Jeanne as `TAX`, or `BOTH`? (currently `TAX`)
