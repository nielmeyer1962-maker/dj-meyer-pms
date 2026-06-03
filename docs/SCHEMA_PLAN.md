# Schema Plan — preparing the model for the real client data

Design proposal for the schema the import needs. **Design only — nothing here is
built yet.** Source mapping and caveats live in [DATA_SOURCES.md](DATA_SOURCES.md).
Niel reviews and approves each ticket before it is implemented (per the working
agreement in `CLAUDE.md`).

## Principles (match the existing codebase)

- Typed `Mapped[...]` columns; `Enum` for categoricals.
- FKs: `ondelete="RESTRICT"` to `clients` (never lose history), `ondelete="SET NULL"`
  to `staff` (offboarding is routine) — same as `ObligationInstance` / `Task`.
- Cross-field invariants via `@validates` + `before_insert`/`before_update` events.
- One Alembic migration per ticket. Tests required for any logic.
- Each ticket is a self-contained chunk: model + migration + tests, green before the next.

---

## Ticket A — Client allocation + CIPC fields  *(do first; independent)*

**Why:** the Master Client List carries `Staff Member`, `CIPC Month`, and `Due Day`,
none of which the `Client` model can hold today. This unblocks company import and
lets the obligation engine assign work automatically.

**New columns on `clients`:**

| Column | Type | Notes |
|---|---|---|
| `allocated_staff_id` | `int \| None`, FK `staff.id` `SET NULL`, indexed | The owning tax/accountant ("Staff Member" / QB "Rep"). |
| `cipc_anniversary_month` | `SmallInteger \| None` (1–12) | Incorporation-anniversary month → drives the CIPC annual return. |
| `cipc_anniversary_day` | `SmallInteger \| None` (1–31) | Anniversary day. |

**Relationship:** `allocated_staff = relationship("Staff")`.

**Invariants (event listener, mirroring the year-end pairing):**
- `cipc_anniversary_month` / `cipc_anniversary_day` both set or both `None`.
- Day valid for month (reuse the `calendar.monthrange` check from `client.py`).
- CIPC fields only meaningful for `PTY_LTD` / `CC` — document; soft-validate.

**Engine hook (later, not this ticket):** the obligation generator defaults
`obligation.assignee_id` to `client.allocated_staff_id`, **except** the CIPC annual
return, which always goes to Tsego (existing locked rule).

**Tests:** pairing invariant, day-range, `SET NULL` on staff delete, the CIPC-vs-Tsego
default once the engine hook lands.

---

## Ticket B — Client contact fields  *(independent)*

**Why:** the QuickBooks export carries contact details the model can't hold.

**New columns on `clients`** (all nullable): `contact_person`, `phone`, `mobile`,
`email`, `physical_address` (Text), `postal_address` (Text).

**QB mapping:** `First Name`+`Last Name` → `contact_person`; `Main Phone` → `phone`;
`Mobile` → `mobile`; `VAT Registration Number` → `vat_number` (existing).
⚠️ The seen QB export has **no email / physical address** — columns land now, populate
once the source is confirmed.

**Deferred:** a separate `Contact` table for multiple contacts per client — only if
demand surfaces. No `@` shape check on email yet (matches the `Staff.email` decision).

**Tests:** minimal (nullable columns).

---

## Ticket C — Beneficial Owner / Group model  *(independent; largest)*

**Why:** the `Beneficial Owner Groups` sheet and the Aerocom test group need a way to
group entities under their owners. "**Beneficial Owner = Shareholder**" under the
General Laws Amendment Act 22 of 2022 — treat as synonyms.

**New table `beneficial_owners`:** `id`, `full_name`, `id_type`
(`Enum`: `SA_ID`, `PASSPORT`, `COMPANY_REG`, `CIPC_AR_REDACTED`), `id_value` (String,
**sensitive**), `notes`. Accept all four ID formats — **never drop foreign nationals.**

**New link table `beneficial_ownerships`** (many-to-many entity ↔ owner): `id`,
`client_id` FK `RESTRICT`, `beneficial_owner_id` FK `RESTRICT`,
`percentage` (`Numeric \| None`), `role/notes`; `unique(client_id, beneficial_owner_id)`.

**Grouping:** an owner's entities *are* the group (Aerocom = entities owned by Daniel
Meyer, 17 of them). A separate named-`Group` table is deferred unless multi-owner named
groups are needed.

**Tests:** link uniqueness, FK behaviour, `id_type` enum coverage.

**Open questions:** capture ownership `percentage` now or later? Named groups vs
owner-derived groups?

---

## Ticket D — IT12 / ITR14 return tracking  *(after A; needs Niel's input)*

**Why:** the `It 12 return` sheet tracks individual returns (year, version, SARS status,
filing date). Individuals are `Client(entity_type=INDIVIDUAL)`.

**Approach (recommended):** model income-tax returns as obligation instances — extend
`ObligationType` with `ITR12`, `ITR14`; add `year_of_assessment` (Int) and a richer
SARS-status field to `ObligationInstance` (its current shape is VAT201-specific:
`period_start/end`, `submission/payment_due_date`). Keeps one dashboard.

**Open questions (need Niel):** the exact SARS status vocabulary (e.g. *Revision
submitted*, *Estimate*, *Filed*), and how SARS Estimates/Revisions are treated (the
sheet isolates Estimates from staff production stats).

**Defer** the build until A/B are in and the vocabulary is confirmed.

---

## Sequencing

1. **A** — allocation + CIPC → unblocks company import + obligation assignment.
2. **B** — contact fields → unblocks the QB contact merge.
3. **C** — beneficial owners → unblocks the group model / Aerocom test.
4. **D** — IT12 tracking → after the status-vocabulary decisions.

Staging import (per DATA_SOURCES.md) runs once **A** and **B** are in.

## Consolidated open questions for Niel

1. Source for client **email + physical address** (not in the QB export).
2. `Rep` → `Staff.code` mapping for odd codes (e.g. `CHANT`).
3. Owner role: Niel & Jeanne `TAX` or `BOTH`? (currently `TAX`)
4. Capture ownership **percentage** in Ticket C now, or later?
5. SARS **status vocabulary** for IT12/ITR14 (Ticket D).
