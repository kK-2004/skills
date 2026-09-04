# One-shot: Tavern's embedded MySQL migrations

Use this example to see how raw repository evidence becomes a migration decision and workflow. Do not transplant its paths, SQL format, numbering, database choice, or commands into another project.

## Observed mechanism

At the time this example was recorded, repository evidence establishes:

- `AGENTS.md` requires every schema change to add a new migration and forbids modifying existing migrations.
- Runtime relational data uses MySQL. Its forward-only SQL files are in `internal/store/mysql/migrations`; the current set is `001` through `012`.
- The MySQL store embeds `migrations/*.up.sql` in the Go binary. Its loader parses the numeric filename prefix, sorts numerically, and rejects duplicate versions, gaps, an empty set, and sequences not starting at 1.
- Repository policy narrows the filename convention further to `NNN_lowercase_description.up.sql`. The project validator enforces this exact working-tree form.
- Each initial migration creates `schema_migrations(version, applied_at)`. Store startup reads `MAX(version)`, rejects a database newer than the binary, skips applied versions, executes pending versions in order, and records each version only after all of its statements succeed.
- MySQL DDL may auto-commit even inside the transaction wrapper. A failed multi-statement DDL migration can therefore leave partial schema changes without its version record; migration design must account for that risk.
- Application startup calls `mysql.Open` before the HTTP handler can serve traffic, so pending MySQL migrations and recovery finish before readiness.

## Current migration inventory

| Version | Purpose |
| --- | --- |
| `001_init` | Creates the multi-user base schema and version ledger. |
| `002_widen_legacy_ids` | Widens prefixed identifiers and dependent foreign-key columns. |
| `003_plaza_publication` | Adds plaza publication/review state and indexes. |
| `004_character_versions` | Adds character versions and conversation version references. |
| `005_model_selection_billing_sessions` | Adds provider billing, template provenance, session indexes, and generation billing snapshots. |
| `006_remove_template_resources` | Adds conversation snapshots, removes template provenance, and drops the template table. |
| `007_conversation_pinning` | Adds per-user conversation pinning and its index. |
| `008_remove_image_crop_params` | Drops obsolete image-framing columns without rewriting objects. |
| `009_interactive_plot_choices` | Adds durable plot choices and generation references. |
| `010_content_center_media` | Adds content-center file IDs and CDN URLs while retaining legacy media references. |
| `011_provider_models` | Splits provider connections from models while preserving legacy model IDs. |
| `012_user_model_availability` | Adds user visibility and ordering for provider models. |

The inventory is descriptive evidence, not a permanent version oracle. Always enumerate the current checkout again before allocating a version.

## Exceptional upgrade phase

Migration `006` cannot safely run as ordinary DDL alone because it drops the legacy `templates` table. When the current database version is below 6, `mysql.Open`:

1. applies pending schema migrations below `006`;
2. runs `BackfillCharacterVersions` and `MigrateTemplatesToCharacters` in store code;
3. applies `006` and every later pending migration;
4. recovers interrupted generations before returning the ready store.

The business transformation uses deterministic IDs, consistency checks, transactions, and idempotent behavior. This illustrates why discovery must inspect orchestration code as well as migration files: numeric file order alone does not describe the full upgrade.

## Project-specific validation

`make validate-migrations` runs `scripts/validate-migrations.sh`. The script:

1. enumerates the authoritative MySQL migration directory, including untracked files;
2. enforces the exact three-digit forward-only filename form;
3. detects non-file entries, empty sets, duplicates, gaps, and sequences not starting at `001`;
4. runs a narrowly targeted Go test that calls the production MySQL `loadMigrations` implementation;
5. never opens a database.

Migration-specific Go tests separately preserve semantic invariants such as supported MySQL defaults, statement ordering, additive-only changes, snapshot preservation, and safe provider/model conversion. Full integration tests may clear real test tables and require explicit permission and intentionally configured services.

## One-shot example

Example request: "Add an optional `last_used_at` timestamp to provider models."

1. Read repository instructions and trace the field's persistence path. Confirm it changes the runtime MySQL schema.
2. Inspect the migration loader, startup store, current files, validator, and relevant compatibility tests. Run `make validate-migrations`; suppose it confirms MySQL `001–012`, so the candidate version is `013`.
3. Search the complete working tree again for version `013`, including untracked files. If free, create `internal/store/mysql/migrations/013_provider_model_last_used_at.up.sql`; never edit `012`.
4. Add only the required MySQL DDL, choosing nullability/default behavior from rollout needs and existing data. Do not add a down file because this project is forward-only.
5. Add a focused compatibility assertion if the change has a non-obvious invariant—for example, existing models must remain valid and the migration must not update historical generation snapshots.
6. Run `make validate-migrations`, relevant focused tests, and the repository-required backend test command. Do not configure destructive integration-test variables or point migration commands at a shared database without explicit permission.
7. Inspect the final diff and recheck the version after any merge or rebase. Report the new file, why a migration was required, the version evidence, and validation results.

This one-shot demonstrates the reasoning shape: discover actual mechanics, choose the correct store, allocate from current evidence, preserve historical migrations, separate business movement when necessary, and verify through both structural checks and the production loader.
