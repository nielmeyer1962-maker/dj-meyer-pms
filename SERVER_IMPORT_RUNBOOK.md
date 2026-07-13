# Server Import Runbook — Client Data Load (claudedb)

Go-live step 1, **server leg**. Loads ~805 clients into the production DB on **claudedb**
via the `flask import-clients` CLI (Ticket 10). Run top to bottom.

**Abort rule (every step): any deviation from an expected result = STOP, do not improvise,
bring the exact output back to chat before continuing.**

Prereqs: PR #16 merged to `main`; the 9-row staff ceremony (Phase 3) already seeded on the
server; you have SSH + psql access to claudedb.

Fill in before starting:
- `<user>`  — your SSH user on claudedb
- `<unit>`  — the app's systemd unit (find: `systemctl list-units | grep -i meyer`)

---

## 0. Every shell: venv + env (before ANY flask/psql command)

    cd /opt/dj-meyer-pms
    source .venv/bin/activate
    systemctl cat <unit> | grep EnvironmentFile        # note the path it prints
    set -a; source <EnvironmentFile-path>; set +a      # loads real DATABASE_URL + SECRET_KEY

**Do NOT set FLASK_DEBUG on the server.** The real SECRET_KEY is in the env file; debug
mode would weaken the running app. (FLASK_DEBUG was only a local-dev shortcut.)

## 1. Back up the database FIRST

    pg_dump -Fc -d "$DATABASE_URL" -f "djmeyer_pms_pre-import_$(date +%Y%m%d-%H%M%S).dump"
    ls -lh djmeyer_pms_pre-import_*.dump               # confirm it exists, non-trivial size

Custom format (`-Fc`) → restore later with `pg_restore` (step 8).

## 2. Update code + schema

    cd /opt/dj-meyer-pms
    git pull
    flask --app run db upgrade
    flask --app run db current                         # MUST print: d7c2f4b9a1e3 (head)

**GATE:** if `db current` != `d7c2f4b9a1e3`, STOP.

## 3. Verify the staff roster (allocation depends on it)

    psql "$DATABASE_URL" -c "SELECT count(*) FROM staff;"   # expect 9

**GATE:** must be `9`. If not, the roster isn't seeded — STOP (importing now would leave
every client unallocated).

## 4. Copy the two source spreadsheets

Local sizes — record now, verify after copy:
- `TSEGO_CIPC_LIST_updated.xlsx` — **80,840 bytes**
- `FINAL FINAL FINAL IT12 LIST(AutoRecovered)      Cherry latest update.xlsx` — **127,484 bytes**

On the server:  `mkdir -p /opt/dj-meyer-pms/import-data`

From your LOCAL machine:

    scp "C:\Users\Niel Meyer\dj-meyer-pms\Excell files to be imported into PMS\TSEGO_CIPC_LIST_updated.xlsx" <user>@claudedb:/opt/dj-meyer-pms/import-data/
    scp "C:\Users\Niel Meyer\dj-meyer-pms\Excell files to be imported into PMS\FINAL FINAL FINAL IT12 LIST(AutoRecovered)      Cherry latest update.xlsx" <user>@claudedb:/opt/dj-meyer-pms/import-data/

Verify integrity on the server (sizes must match EXACTLY):

    stat -c '%s  %n' "/opt/dj-meyer-pms/import-data/TSEGO_CIPC_LIST_updated.xlsx"                                        # expect 80840
    stat -c '%s  %n' "/opt/dj-meyer-pms/import-data/FINAL FINAL FINAL IT12 LIST(AutoRecovered)      Cherry latest update.xlsx"   # expect 127484

**GATE:** any size mismatch → STOP, re-copy.

## 5. DRY RUN both (no writes) — PASS GATE

    flask --app run import-clients companies  "/opt/dj-meyer-pms/import-data/TSEGO_CIPC_LIST_updated.xlsx"
    flask --app run import-clients individuals "/opt/dj-meyer-pms/import-data/FINAL FINAL FINAL IT12 LIST(AutoRecovered)      Cherry latest update.xlsx"

**PASS GATE — must match EXACTLY:**
- companies:   real rows **447** / flagged **27**
- individuals: matched for insert **358** + skipped duplicates **8** / flagged **9**

Any other numbers → STOP, bring the report to chat. Do NOT commit.

## 6. COMMIT both

    flask --app run import-clients companies  "/opt/dj-meyer-pms/import-data/TSEGO_CIPC_LIST_updated.xlsx" --commit
    flask --app run import-clients individuals "/opt/dj-meyer-pms/import-data/FINAL FINAL FINAL IT12 LIST(AutoRecovered)      Cherry latest update.xlsx" --commit

**Expected:**
- companies:   inserted **447** / updated **0** / skipped **0**
- individuals: inserted **358** / updated **0** / skipped **0**

Any deviation → STOP.

## 7. Browser check

Open the app → Clients page. Expect **~805** clients. Spot-check several names and their
staff allocations against the source lists.

## 8. Rollback (only if a step failed)

    pg_restore -c -d "$DATABASE_URL" djmeyer_pms_pre-import_<timestamp>.dump

---

Post-import: VAT201 generation must wait for the VAT go-live reconciliation (PROJECT_PLAN.md,
Ticket 10) — do not switch it on from imported data alone.
