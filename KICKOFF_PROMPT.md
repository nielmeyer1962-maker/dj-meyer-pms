# Kickoff prompt for Claude Code

Paste the block below as your first message to Claude Code, after you've added `CLAUDE.md` and `PROJECT_PLAN.md` to the empty repo.

---

```
Read CLAUDE.md and PROJECT_PLAN.md in this repo before doing anything else.

Then do exactly these three things and stop:

1. Recommend a tech stack for Phase 1. Five to ten lines. Cover language,
   web framework, database, frontend approach, deployment target. Justify
   each choice against the constraints in CLAUDE.md (single firm, ~10
   users, maintained by one person with AI help, runs in South Africa,
   needs Zoho / Gmail / n8n integration later). Default to boring and
   well-supported.

2. Propose a minimal repo layout — directory tree only, no code yet.

3. List the first three implementable tickets you would tackle, in
   order, with a one-line description and rough effort (S / M / L)
   for each.

Do not scaffold, do not install anything, do not write code. Wait for
my approval on stack and tickets before any of that.
```

---

## After you approve the stack

Use prompts like these for the first three tickets. Keep each one in its own Claude Code session if the tickets are large — fresh context, less drift.

**Ticket 1 — repo scaffold and CI**

```
Scaffold the repo per the layout you proposed. Add a README with setup
instructions, a .gitignore appropriate for the chosen stack, a
formatter / linter config, and a minimal CI workflow that runs tests
and the linter on push. Do not add any application code yet beyond the
"hello world" needed to prove the pipeline runs. Show me the diff
before committing.
```

**Ticket 2 — Client model and CRUD**

```
Implement the Client model exactly as specified in PROJECT_PLAN.md.
Add a migration, a repository / service layer, and the minimum UI to
create, list, edit, and archive a client. No obligations yet. Include
tests for the model invariants (e.g. year_end month is 1–12, day is
valid for the month, registrations is a subset of the allowed set).
```

**Ticket 3 — Obligation engine, no UI**

```
Build the obligation generation logic per PROJECT_PLAN.md. Pure
functions where possible: given a Client, return the list of
ObligationInstances for the next twelve months. Encode each due-date
rule from the table in PROJECT_PLAN.md, with a comment citing the
source for each. Add unit tests covering: a Pty Ltd with March
year-end and VAT, an individual on provisional, and a PAYE-registered
employer. No UI yet — we will wire this in after the logic is solid.
```

## How to actually run Claude Code

1. Install Claude Code on your machine and authenticate. Confirm the current install command at `https://docs.claude.com` — it changes occasionally.
2. Create a new GitHub repo (private). Clone it locally.
3. Drop `CLAUDE.md` and `PROJECT_PLAN.md` into the repo root and commit.
4. Open the folder in Cursor. Open Cursor's terminal.
5. Run `claude` in that terminal to start Claude Code in this project.
6. Paste the kickoff prompt above.
7. Read its three answers carefully, push back where the reasoning is thin, and only then approve. The biggest single thing you can do for code quality is treat the first reply as a proposal, not a result.

## Notes on staying out of the LedgerPro trap

- Phase 1 ships before anything else is discussed. If a "wouldn't it be nice if..." appears, it goes into a `BACKLOG.md` and stays there until Phase 1 is in production use at the firm.
- One person is going to maintain this. Every dependency is a tax. Push back on Claude Code if it suggests four libraries where the standard library will do.
- The first user is you. Use it for one week on real client data before showing it to anyone else at the firm.

## Where n8n actually fits

Not in building the system. The natural integration point is around Phase 2:

- **Trigger:** a deadline instance is `due_date - 7 days` and still `not_started`.
- **n8n workflow:** call the system's API → format an email → send via Gmail → (optionally) post to a Slack or Teams channel for the assignee → log back to the instance via webhook.

This way the Phase 1 system stays small and synchronous, and n8n owns the messy "fan out to a dozen channels" logic where it belongs.
