# client-data/ — local client data (never committed)

This directory is the local drop point for the firm's canonical client file
(the ~447-company CSV) and any other raw client spreadsheets/exports.

**Nothing in here is committed** — the repository is public and this data is
subject to POPIA. `.gitignore` ignores the entire directory except this README.

## Importing

Place the canonical CSV here (e.g. `client-data/clients.csv`) and run:

```
flask clients import client-data/clients.csv          # writes changes
flask clients import client-data/clients.csv --dry-run # report only, writes nothing
```

After an import, generate every active client's obligations:

```
flask clients regenerate-all            # writes changes
flask clients regenerate-all --dry-run  # report only
```

Keep the master copy on `Y:\`; treat anything here as a disposable local working copy.
