# Phase 3 — credential ceremony (2026-07-10)

App live at `http://192.168.1.246` (Phase 2b closed, see `deploy-log-2026-07-08.md`).
Target `djmeyer@192.168.1.246` (`claudedb`, Ubuntu 24.04). Deploy root `/opt/dj-meyer-pms`.

**Division of labour (unchanged from deployment):** Claude runs only non-privileged,
read-only or non-secret DB work over `ssh -o BatchMode=yes` key auth. **Niel runs every
command that sets a password or admin flag, in his own interactive ssh window** — passwords
are generated/typed server-side only and NEVER transit the Claude chat.

---

## Auth model recap (read-only inspection)

- **No `User` model.** Auth is on **`Staff`** (`app/models/staff.py`), subclass of Flask-Login
  `UserMixin`. Fields: `code`, `full_name`, `email` (unique, nullable — the login id),
  `role` (`TAX`/`SECRETARIAL`/`BOTH`), `password_hash` (nullable — no hash ⇒ can't log in),
  `is_admin` (gates Settings bp + client archive), `active` (soft-delete, tied to `is_active`).
- **Row creation:** no self-registration, no admin UI. Rows come only from `seed.py`
  (gitignored, dev-only) — so NOT present on the server. Created inline this session instead.
- **Credentials:** `flask staff set-password <email>` (prompts twice, hidden, min 10 chars)
  and `flask staff set-admin <email> --on/--off` — both look up an existing row by email.
- **Password change:** self-service at `/account/password` (needs current password). No
  change-on-first-login mechanism.
- **Hashing:** werkzeug `generate_password_hash` (werkzeug 3.x default = scrypt), salted, one-way.

## Decisions (Niel, final)

1. **9 accounts:** Niel, Jeanne-Marie, Caroline, Quinlyn, Stacey, Dewald, Candice, Tsego,
   plus a shared **RECEPTION** account (standard rights, never admin — noted that a shared
   login weakens the per-user audit trail; accepted deliberately).
2. **Admin:** `niel@djmeyer.co.za` and `jeanne-marie@djmeyer.co.za` only.
3. **`seed.py` corrections:** DEWALD Roux (`dewald@`), Candice (`candice@`), Stacey Roux
   confirmed, Reception (`reception@`). RECEPTION `role` = `BOTH` (role gates nothing in code
   today — descriptive only).

---

## Step 0 — pre-state probe (Claude, read-only) — DONE

`seed.py` absent on server (gitignored, not cloned). `staff` table empty (`STAFF_COUNT 0`).

## seed.py edit (local dev canonical roster) — DONE

Local `seed.py` updated: CANDI + DEWALD (renamed from DEWALT/"Dewalt") given emails;
new RECEPTION row. File is gitignored, so this is dev-only bookkeeping — it does not reach
the server.

## Step 1 — create 9 rows on server (Claude, inline, no secrets) — DONE

Option A chosen (inline `flask`/`python`, no file on the box). Fed the roster to
`.venv/bin/python` in script mode (REPL `flask shell` mangled the multi-line block; script
mode via stdin works). Idempotent on `code`. `load_dotenv("/opt/dj-meyer-pms/.env")` needed
an explicit path (stdin has no frame for `find_dotenv()`).

Result: `INSERTED 9 SKIPPED 0`. Verify — all 9 `active`, `-` (no admin), `NO-HASH`:
```
CANDI candice@djmeyer.co.za TAX - active NO-HASH
CAROLINE caroline@djmeyer.co.za TAX - active NO-HASH
DEWALD dewald@djmeyer.co.za TAX - active NO-HASH
JEANNE jeanne-marie@djmeyer.co.za TAX - active NO-HASH
NIEL niel@djmeyer.co.za TAX - active NO-HASH
QUINLYN quinlyn@djmeyer.co.za TAX - active NO-HASH
RECEPTION reception@djmeyer.co.za BOTH - active NO-HASH
STACEY stacy@djmeyer.co.za TAX - active NO-HASH
TSEGO tsego@djmeyer.co.za SECRETARIAL - active NO-HASH
```

---

## Step 2 — set passwords (NIEL, interactive ssh window) — PENDING

Run once per account. Each prompts twice, hidden; ≥10 chars. Passwords typed server-side only.
```bash
cd /opt/dj-meyer-pms
.venv/bin/flask --app run staff set-password niel@djmeyer.co.za
.venv/bin/flask --app run staff set-password jeanne-marie@djmeyer.co.za
.venv/bin/flask --app run staff set-password caroline@djmeyer.co.za
.venv/bin/flask --app run staff set-password quinlyn@djmeyer.co.za
.venv/bin/flask --app run staff set-password stacy@djmeyer.co.za
.venv/bin/flask --app run staff set-password dewald@djmeyer.co.za
.venv/bin/flask --app run staff set-password candice@djmeyer.co.za
.venv/bin/flask --app run staff set-password tsego@djmeyer.co.za
.venv/bin/flask --app run staff set-password reception@djmeyer.co.za
```

## Step 3 — grant admin (NIEL, interactive) — PENDING
```bash
.venv/bin/flask --app run staff set-admin niel@djmeyer.co.za --on
.venv/bin/flask --app run staff set-admin jeanne-marie@djmeyer.co.za --on
```

## Step 4 — Claude re-probe (read-only) — DONE
Verified 2026-07-10. `STAFF_COUNT 9`; `MISSING_HASH: none` (all 9 have a hash);
`ADMINS: ['jeanne-marie@djmeyer.co.za', 'niel@djmeyer.co.za']` — exactly the two intended,
no others. All 9 `active`. No passwords revealed.

## Step 5 — Niel smoke-test one real login over the LAN (browser). — DONE
PASS (2026-07-10, Niel): logged in as niel@ over the LAN, Obligations dashboard renders,
nav + filters working, empty state correct (no clients loaded yet).

---

## Phase 3 — CLOSED (2026-07-10)

All 9 logins created with password hashes; admins = niel@ + jeanne-marie@ only; real login
verified over the LAN. `seed.py` is gitignored (roster lives only in the server DB).
Open follow-ups (not blocking): no forced change-on-first-login — staff can self-rotate at
`/account/password`; DHCP reservation / static IP for a stable endpoint still pending.
