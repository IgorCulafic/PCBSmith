# Repository retention and ownership

Status: 2026-09-05. This implementation uses classification and indexes; it does not
move proof directories for appearance or delete uncertain historical material.

| Material | Disposition | Reason / next condition |
| --- | --- | --- |
| src, tests, tools, schemas, setup/config and maintained docs | Keep source, including local-only files | Stage only an intentionally reviewed set; required test/source files may be untracked. |
| Native designs, outputs, experiments and cited ledgers/figures | Retain exact paths and bytes | Fresh attempts use new paths. Migration requires complete old/new hashes and reference compatibility. |
| Unpublished papers 01–04 and related raw/failed runs | Retain privately | Excluded from software distributions; no publication or model collection by this change. |
| old_files and old conversation logs | Keep as private historical references | No exhaustive duplication/reference proof exists to justify removal. |
| ai_assets, models and vendor/native tool installations | Keep required/local assets | Source/license/hash policy applies; size alone is not a removal criterion. |
| ai_assets/local-ai-config.json | Keep local, untracked | Safe example retained. Original bytes preserved; only its index removal is staged. |
| .venv and .tmp/uv-python | Protect active runtime chain | A frozen independent environment was tested, but its base interpreter still relies on the retained .tmp runtime. No runtime retirement is justified yet. |
| Known Python/type/lint/test caches | Candidate, not automatically expendable | tools/clean_workspace.py requires bounded targets, protected-reference checks and a reviewed manifest. No cleanup deletion was performed. |

A private path-level CSV in the review implementation evidence records Git state,
size/hash, classification, original/destination path and retention rationale for the
tracked and nonignored local-only files. The earlier full disk inventory covers
ignored runtime/history areas; their hashes/removal eligibility are not assumed.
No file is classified for removal merely because it is ignored or absent from Git.

Before a future migration: select one category, trace consumers/citations, verify
backup restoration if it is relied upon, prepare an exact old-to-new map, retain
compatibility where necessary, verify hashes/replays/links, then retire only the
specifically approved old paths. Do not combine a move with changed experiment
results. No migration or destructive cleanup was necessary for the implemented fixes.
