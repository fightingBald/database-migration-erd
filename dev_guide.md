# Developer guide

CLI reference, schema behavior and contributor workflows. For installation and everyday use, see the [README](README.md).

## Environment

Use Python **3.11+** and **D2 0.7.1**. Local validation used Python 3.14; CI is configured for 3.11 and 3.14. Rendering checks the exact D2 version to keep layout behavior reproducible; both `0.7.1` and `v0.7.1` version strings are accepted.

Download D2 from the [official 0.7.1 release](https://github.com/d2lang/d2/releases/tag/v0.7.1). ELK is included; no separate ELK service is needed. `requirements.txt` installs only sqlglot and PyYAML; `requirements-dev.txt` also installs pytest and Ruff.

## CLI reference

```bash
python -m erd_generator SQL_DIR OUTPUT
```

Both paths are required. `SQL_DIR` is the migration directory. The output extension selects what to generate:

| Output | Files written | D2 executable required? |
| --- | --- | --- |
| `./generated/schema.svg` | `schema.svg` and `schema.d2` in `./generated/` | Yes |
| `./generated/schema.d2` | `schema.d2` only | No |

The short command defaults to ELK, clean styling, automatic business/relationship grouping, compact component placement, rightward layout and visible column types. FK and layout YAML are loaded only when explicitly supplied. No example relationships or input/output paths are selected implicitly.

Optional overrides follow the two paths:

```bash
python -m erd_generator ./db/migration ./generated/schema.svg --fk-config ./sample_fk_config.yaml
python -m erd_generator ./db/migration ./generated/schema.svg --direction down
python -m erd_generator ./db/migration ./generated/schema.d2 --hide-types
```

Quote paths containing spaces. Generated files are overwritten by regeneration; edit migrations, FK configuration or generation options rather than the generated files.

| Option | Behavior |
| --- | --- |
| `--style clean\|classic` | D2 visual preset, default `clean`; `classic` restores the original appearance |
| `--hide-types` | Hide SQL column types; retain names and constraints |
| `--show-types` | Explicitly display SQL column types; already enabled for the short command |
| `--fk-config PATH` | Add relationships declared in YAML |
| `--layout-config PATH` | Optional business-group, title and colour overrides; see [business layout](#business-layout) |
| `--direction right\|left\|up\|down` | ELK layout direction, default `right`; after grouping, FK arrows can point either way while retaining their actual meaning |
| `--grouping auto\|none` | Infer business/relationship groups and balance shared hubs, default `auto`; `none` disables those inferences while retaining explicit layout groups and independent component packing |
| `--d2-binary PATH` | Rendering executable, default `d2`; requires SVG output |
| `--render-timeout SECONDS` | Positive timeout per D2 process, default 120; requires SVG output |
| `--force-appendix` | Display tooltip contents in the SVG appendix; requires SVG output |
| `--log-dir PATH` | Write detected SQL/configuration diagnostics to `PATH/parse_log/`; default working directory |

The main command logs table, column and foreign-key counts, rendering version/layout and duration. Invalid options return exit code 2; generation/rendering errors return 1; complete requested output returns 0.

Existing named commands remain supported, including `--render svg` with a `.d2` output:

```bash
python -m erd_generator --migrations ./db/migration --out ./generated/schema.d2 --show-types --render svg
```

Use either the two positional paths or `--migrations` plus `--out`; mixing them is rejected. With named paths, column types are hidden unless `--show-types` is supplied, and a `.d2` output does not render unless `--render svg` is supplied. Named `--out` also accepts `.svg`. CLI and Python `erd_generator.main()` use the same D2-only workflow.

Breaking change: draw.io export, XML extraction/comparison, their scripts and Python export have been removed. `--format`, `--layout`, `--per-row` and `--graphviz-*` are no longer accepted; ELK is fixed. Switch old invocations to `python -m erd_generator SQL_DIR OUTPUT`. There are no compatibility aliases. To restore the removed functionality, restore the previous project version and its dependencies; no database rollback is involved.

## Table and relationship behavior

- The default `clean` style uses blue-grey headers, white table bodies, light separators, dark field names, muted types, teal constraint markers and rounded slate-coloured connections. Connection labels use regular text. The palette and styles are embedded in the D2 source.
- Each table is a D2 `sql_table`; fully qualified names are quoted as one key.
- Primary and foreign-key columns receive PK/FK markers, including both on the same column.
- Single-column, unconditional unique constraints/indexes receive UNQ markers. Composite, partial and expression indexes remain in the notes without incorrectly marking individual columns unique.
- Foreign-key arrows point from referencing columns to referenced columns. Explicit composite keys create one connector per column pair, labeled with a common constraint and pair number.
- Repeated FK declarations are deduplicated. Columns retain their Schema order; table, relationship and note ordering is deterministic.
- Primary keys, complete foreign keys and indexes (including available names, methods and predicates) appear in table tooltips. `--force-appendix` makes the notes visible without hovering.
- Self references have explicit `source_column → target_column` labels: D2 0.7.1/ELK may route self loops to table boundaries rather than exact row ports. The project renderer sets `--elk-nodeSelfLoop=100` to leave room for these labels.

D2 handles text quoting, including reserved keywords, dots, quotes, backslashes, Unicode and literal `${...}` sequences.

See [D2 SQL tables](https://d2lang.com/tour/sql-tables/) and [ELK](https://d2lang.com/tour/elk/) for the upstream rendering model.

Use `--style classic` to restore the original D2 appearance. Both presets preserve the same column definitions, constraints and relationship endpoints. The implementation uses [native D2 styles](https://d2lang.com/tour/style/) and [theme overrides](https://d2lang.com/tour/themes/).

### Compact placement

Disconnected tables and independent relationship groups are packed automatically. No extra command-line option is required:

- Tables linked by any validated FK, including YAML relationships, stay inside one packed region. Business-group membership can join otherwise independent components into the same region without inventing FKs. Self references stay with their table.
- Within each region, native ELK places and routes connected business groups and relationship communities. Tables without enough naming or relationship evidence retain their previous flat D2 structure.
- For multiple groups, a pure planner estimates their sizes from names, column counts/types and relationship layers. It compares column counts, balancing the overall aspect ratio and unused area, and places taller groups first to balance column heights.
- Invisible D2 containers separate the outer grid from each group's ELK layout. Tables retain their natural dimensions and font sizes; putting SQL tables directly into a grid would stretch rows/widths, and putting FK endpoints directly in separate grid cells would lose ELK routing. See [D2 grid behavior](https://d2lang.com/tour/grid-diagrams/).
- The renderer uses 16-unit ELK container padding; grids use 48-unit gaps. Sorting and tie-breaking are deterministic. `.d2` generation needs no D2 executable, and layout planning uses only the standard library without mutating Schema.

Size estimates guide packing; they are not a guaranteed canvas ratio. A single large connected graph, exceptionally long labels or one very tall table can still make a wide/tall diagram. A connected graph is not split into grid cells just to meet an aspect ratio. `--direction` controls the ELK layout axis, and `--style classic` changes appearance while keeping automatic packing.

Migration/rollback: generated D2 for disconnected graphs now nests objects under invisible `_erd_column_*` / `_erd_component_*` containers. Visible SQL names, columns, tooltips and FK meanings remain unchanged, but scripts referencing absolute D2 object paths must account for the new prefixes. Use the generator's SVG command for the configured spacing; invoking D2 manually without the padding flag uses D2's larger default container margins. Reverting the compact-layout change and regenerating restores the earlier flat layout; no SQL migration or database rollback is needed.

### Business layout

All bundled examples use a fictional library. Example schemas, roles, table names and relationships are synthetic; use the `demo_library` namespace for new examples. Keep real customer/company SQL, identifiers, local paths and generated diagrams out of fixtures and documentation. Generate example diagrams from the checked-in synthetic SQL.

Automatic business grouping needs no YAML or additional command options. Repeated word prefixes such as `books_*`, `loans_*` and `members_*` can produce named regions with a title, subtle background, matching table headers and a table count. Namespace-qualified titles distinguish the same family in different schemas. Colours are derived from stable group identifiers, so unrelated groups do not rotate the palette. Titles also identify groups when colours are similar.

The deterministic rules are deliberately conservative:

- A family needs at least three tables and meaningful suffix variation, or a root table with meaningful descendants. Matching uses underscore word boundaries and keeps database namespaces separate; it does not confuse `books_*` with `bookshelf_*`.
- Numeric/version-only suffixes do not establish business meaning. Common `t`/`tb`/`tbl`/`table` prefixes are skipped. A rootless wrapper containing multiple eligible subfamilies yields the more specific families; this decision uses that prefix's own subtree, not unrelated table counts.
- Strong, distributed external relationships can reject a misleading naming family. Repeated constraints, composite-key width and self references do not inflate this evidence. Widely shared hubs are discounted instead of making every named domain appear incoherent.
- Clear naming can group tables without any FK. Weak or conflicting names fall back to neutral relationship communities and independent-table packing. No business descriptions or foreign keys are invented, and no model/network call is involved.
- Large named regions retain inferred relationship communities inside them. Only one business level and one inner community level are emitted; all ancestor-level FK endpoints remain outside cross-cell grids.

These are presentation inferences, not business-domain declarations extracted from SQL. `t001`-style names cannot reveal their business meaning. Adding or removing related tables can change inferred membership and geometry; identical input/configuration remains deterministic.

To correct an exception, create a small override file and pass it explicitly:

```bash
python -m erd_generator ./db/migration ./generated/schema.svg --layout-config ./erd-layout.yaml
```

```yaml
groups:
  books:
    tables: ["demo_library.books"]
    label: Books
    color: blue
  loans:
    tables: ["demo_library.loans", "demo_library.loan_*"]
    color: gold
```

Only `tables` is required per group. `label` defaults to the group key; colour is automatic unless overridden with `blue`, `gold`, `green`, `violet`, `slate`, `rose`, `teal` or `orange`. Colours apply to the region and its table headers with either clean or classic styling. Unmatched tables continue to be inferred automatically. Explicit membership is never changed by inference or hub placement, and a group can contain tables from separate FK components.

Selectors first match an exact Schema table name, then use case-sensitive shell-style wildcards (`*`, `?`, `[abc]`). Use complete qualified names; there is no unqualified-name fallback. Exact names containing wildcard characters take precedence. Overlaps between groups, zero-match selectors, empty files/groups/lists, unknown fields, invalid values, duplicate YAML keys and YAML merge keys are errors. These errors are reported before either existing output is replaced. There is no implicit configuration-file search.

For Python callers, use `build_d2(schema, layout_config=load_layout_config(path))`, importing `load_layout_config` from `erd_generator.layout_config`. Direct immutable `LayoutConfig`/`GroupRule` values are also supported. File loading stays outside the pure D2 builder; source-only generation still needs no D2 executable.

To roll back automatic business/community/hub layout, add `--grouping none`. Explicit overrides remain active; remove `--layout-config` as well to restore the ungrouped workflow. Generated D2 may gain stable `_erd_group_*` prefixes; continue regenerating rather than relying on old object paths. SVG paths and the CI publication sequence are unchanged.

### Related-table grouping

The default `--grouping auto` also examines remaining connected components and the interiors of business regions with **12 or more tables**:

- A pure greedy modularity calculation groups tables with many internal links and relatively few links to the rest of the graph. Each table pair contributes once; FK direction, duplicate/parallel constraints, composite key width and self references do not distort grouping.
- Grouping requires at least two groups containing three or more tables and modularity of at least 0.15. Small diagrams, a single star and graphs without sufficiently distinct communities keep their previous layout.
- A shared table linked to at least six neighbors across three or more groups, with fewer than half its neighbors in its assigned group, is placed separately. This avoids arbitrarily attaching a common identity/tenant table to one inferred domain.
- Related tables are nested in invisible **regular D2 containers**. Native ELK routes both internal and cross-group edges. These connected groups never become separate grid cells, which would replace ELK routing with straight center-to-center segments.
- Deterministic graph coloring orders adjacent tables and groups into a few layers. The D2 emitter uses both `child -> parent` and `parent <- child` so layout need not follow one long FK chain. Arrowheads still point from the referencing field to the referenced field; every FK, composite pair, column marker and tooltip is retained.
- Singleton groups linked to at least three other groups are candidates for a central band, with neighboring groups arranged on both sides. Adjacent hubs receive distinct layers. Estimated group dimensions balance independent neighbors or layer classes; this guides ELK rather than fixing a node at an exact coordinate.

This relationship-community stage uses declared or configured FKs; the separate business-family stage also uses names. Neither stage invents missing FKs. Large hubs, dense relationships and long labels can still create long routes; automatic grouping does not guarantee the best layout for every schema. ELK may enlarge heavily connected tables to make space for ports. Use existing `--fk-config` support when meaningful relationships are absent from SQL.

No additional runtime dependency or D2 executable is needed for source generation. The planner is deterministic and does not modify Schema. Validation checks rendered table regions, FK field rows and actual SVG arrowheads, not just D2 strings. A 40-table / 71-FK regression fixture also compares canvas area and routed lengths against `--grouping none`.

Migration/rollback: grouped D2 adds `_erd_group_*` object-path prefixes and may use `<-` as well as `->`. Tools reading generated D2 must account for both connection directions. Add `--grouping none` (or `build_d2(..., grouping="none")`) and regenerate to restore the previous connected-graph layout. Disconnected component packing and SQL processing are unaffected; no database rollback is involved.

The [business layout design](docs/plans/d2-business-layout.md) records the engine constraints and prototype comparisons. [Implementation validation](docs/validation/d2-business-layout.md) records the current checks separately from those prototypes.

## Relationships without database FK constraints

Three sources are supported:

1. Native inline or table-level `FOREIGN KEY` definitions.
2. Column comments such as `-- FK demo_library.members(id)`.
3. Additional YAML relationships supplied through `--fk-config`.

```yaml
demo_library.members:
  fks:
    - [membership_type_id, demo_library.membership_types, id]
    - [sponsor_id, demo_library.members, id]

demo_library.loan_items:
  fks:
    - [loan_id, demo_library.loans, id]
    - [book_id, demo_library.books, id]
```

Each triple is `[local_column, target_table, target_column]`. Composite relationships use `[[tenant_id, user_id], memberships, [tenant_id, id]]`. The historical two-item YAML shorthand `[id, target_table]` means the same column name on both sides.

A short table name must resolve unambiguously. Wrong qualified names, unknown columns and malformed entries fail generation; use explicit qualified names when schemas share table names. YAML adds relationships and does not replace conflicting SQL declarations.

SQL `REFERENCES table` without column names is supported when the target has a single primary-key column. Omitted composite references fail clearly because the existing Schema stores primary keys as an unordered set; it cannot safely infer the declaration order. Explicit composite reference columns are supported.

## PostgreSQL blocks and setup statements

Statement splitting uses the pinned sqlglot PostgreSQL tokenizer. It preserves `$$...$$` and `$tag$...$tag$` literals, quoted strings/identifiers and nested block comments, so their internal semicolons do not split statements. Tags are case-sensitive. Unterminated tokens produce a sanitized diagnostic with the input file and statement line.

| Input | ERD behavior |
| --- | --- |
| `GRANT`, `REVOKE`, `ALTER DEFAULT PRIVILEGES` | Skip permission changes. |
| `CREATE ROLE`, `CREATE USER` | Skip account creation; credentials are not logged. |
| Standalone `CREATE SCHEMA`, including `IF NOT EXISTS` and `AUTHORIZATION` | Skip the namespace declaration. |
| `CREATE FUNCTION` / `CREATE PROCEDURE` with ordinary string or dollar-quoted bodies | Skip the definition; never apply its body as if the routine had been called. |
| Dollar-quoted, straight-line PL/pgSQL `DO ... BEGIN ... END` | Apply the existing supported table/index DDL subset in order. Permission/setup commands, `NULL` and literal-only `RAISE NOTICE`/`INFO`/`DEBUG`/`LOG`/`WARNING` statements are skipped. |
| Wholly ERD-neutral `DO` blocks with role checks or `EXECUTE format(...)` | Skip only after checking every branch, command template and argument against the rules below. |
| Other conditional/dynamic blocks, declarations, loops, nested `BEGIN` blocks, exception handlers or calls | Report unsupported input; do not assume which schema changes occur. |
| `CREATE SCHEMA` containing object definitions, `ALTER SCHEMA`, `DROP SCHEMA` | Report unsupported input; these can change diagram objects. |

For example, this static block is supported:

```sql
CREATE SCHEMA app;
DO $migration$
BEGIN
    CREATE TABLE app.items (id integer PRIMARY KEY);
    ALTER TABLE app.items ADD COLUMN label text;
END;
$migration$;
```

The optional `LANGUAGE plpgsql` clause may appear before or after the dollar-quoted body. The final `END` may omit its semicolon. Migration comments such as `-- +migrate StatementBegin` and `-- +migrate StatementEnd` remain comments.

Common role/permission setup is supported, including the complete [library reader migration regression fixture](tests/fixtures/postgres_role_setup.sql):

```sql
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'demo_library_reader') THEN
        CREATE ROLE demo_library_reader NOLOGIN;
    END IF;
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO demo_library_reader', CURRENT_DATABASE());
END
$$;
```

The neutral-block allowlist has deliberately bounded rules:

- Conditions may be `TRUE`/`FALSE`, optionally preceded by `NOT`, or `[NOT] EXISTS (SELECT ... FROM pg_roles WHERE rolname = 'name')`. `pg_authid`/`rolname` and `pg_user`/`usename` also qualify; `pg_catalog.` is optional. The SELECT list may be empty, `1`, `*` or the name column. Aliases, joins, additional predicates and arbitrary functions are unsupported.
- `IF`/`ELSIF`/`ELSE` and nested `IF` are checked across **all** branches; no condition is evaluated. Every statement must be one of the setup/no-op commands above or an accepted `EXECUTE`. A block mixing these conditional/dynamic constructs with table/index DDL remains unsupported.
- `EXECUTE` accepts an ordinary/dollar-quoted constant SQL string or `format`/`pg_catalog.format` with a constant template. Every SQL command in that string must be ERD-neutral. A template containing both a grant and a table change is rejected.
- Supported format slots are `%I`, `%L`, positional forms such as `%1$I`, and `%%`. Slots must occupy complete SQL tokens outside existing strings, quoted identifiers or comments. `%s`, width/flags, concatenation, variable templates and `USING` are unsupported. These boundaries follow PostgreSQL's [format quoting rules](https://www.postgresql.org/docs/current/functions-string.html#FUNCTIONS-STRING-FORMAT).
- Arguments may be ordinary/dollar-quoted string literals, `CURRENT_USER`, `CURRENT_ROLE`, `SESSION_USER`, `CURRENT_DATABASE()` or `CURRENT_SCHEMA()`; the two function calls may use `pg_catalog.`. Every argument is checked, including unused ones. Arbitrary calls, subqueries and casts are rejected.

This is static schema extraction, not a PL/pgSQL interpreter or a database execution check. Loops, `CALL`, `PERFORM`, declarations and nested `DO` remain unsupported. The rules assume standard PostgreSQL catalog/builtin semantics; unqualified names retain the parser's existing `search_path` limitations. Use qualified names when schema identity matters.

Supported `DO` blocks containing structural DDL are applied to a temporary Schema copy. If any statement in the block fails, none of its changes reach the caller's Schema. The loader can still collect later statements for diagnostics, but any error prevents D2/SVG output from being replaced. Use ordinary DDL or a reviewed schema snapshot for migrations whose structural effects require runtime evaluation; there is no option to silently ignore unknown blocks.

The allowlist classifies structural impact and does not validate every PostgreSQL permission or role option. Skipped command categories and static block completion are logged at DEBUG without SQL payloads. No additional dependencies, CLI flags or database connection are required. Reverting the neutral-block extension restores the previous rejection of conditional/dynamic blocks while retaining dollar quoting and static DDL support; no database rollback is involved.

## Migration loading and errors

Versioned files named `V<number>__description.sql` are ordered numerically, including dot/underscore version components; `V2` precedes `V10`. Non-versioned filenames follow versioned files in path order. This is a file ordering contract, not a complete Flyway migration-history implementation. Keep version names unique and include the complete migration history.

The loader reads UTF-8 strictly. The D2 workflow stops on detected SQL/configuration failures or invalid relationships before overwriting source output. Diagnostics include file/object context and omit SQL/YAML payloads from generator console/file logs.

Rendering explicitly requests ELK and ignores ambient `D2_*`/`ELK_*` environment configuration. It has no fallback to another backend or layout. SVG is rendered to a temporary file and verified before replacing the target. If rendering fails, the generated `.d2` is retained, the previous SVG is unchanged, and the command reports that the SVG was not updated. Source and SVG replacement are separate operations; automation must check the exit code.

No SQL or diagram is uploaded to an online service by these commands.

## CI and Docusaurus

Run the generator before each documentation build, using the migration files from that CI checkout:

```text
Migration SQL → generator + D2/ELK → static/img/schema.svg → Docusaurus build → existing site deployment
```

This documents the schema described by the checked-out migrations, not the live database. Include the complete migration history. No database connection, Docusaurus plugin or new generator option is needed. This repository has generation checks in [.github/workflows/check.yml](.github/workflows/check.yml), but does not contain a Docusaurus site or its deployment pipeline.

### Generate before building the site

The following steps belong in the **application/documentation repository's existing GitHub Actions job**, after its checkout and Node setup. This example assumes an Ubuntu x64 runner, migrations in `db/migration/` and an npm-based Docusaurus site with a lockfile in `docs-site/`. Change those two paths to match your repository. Keep your site's existing Node version and deployment steps.

```yaml
- name: Check out the ERD generator
  uses: actions/checkout@v7.0.1
  with:
    repository: fightingBald/database_migrate_UML_generator
    ref: 85756bb952b4ca9d70d01882b9ac5839ef718cd4
    path: .tools/erd-generator
- uses: actions/setup-python@v7.0.0
  with:
    python-version: "3.11"
- name: Install generator dependencies
  working-directory: ${{ github.workspace }}
  run: python -m pip install -r .tools/erd-generator/requirements.txt
- name: Install verified D2 with bundled ELK
  shell: bash
  run: |
    archive="$RUNNER_TEMP/d2-v0.7.1-linux-amd64.tar.gz"
    curl --fail --location --retry 2 \
      https://github.com/d2lang/d2/releases/download/v0.7.1/d2-v0.7.1-linux-amd64.tar.gz \
      --output "$archive"
    echo "eb172adf59f38d1e5a70ab177591356754ffaf9bebb84e0ca8b767dfb421dad7  $archive" | sha256sum --check -
    tar -xzf "$archive" -C "$RUNNER_TEMP"
    echo "$RUNNER_TEMP/d2-v0.7.1/bin" >> "$GITHUB_PATH"
- name: Generate database diagram
  working-directory: ${{ github.workspace }}
  env:
    PYTHONPATH: ${{ github.workspace }}/.tools/erd-generator
  run: python -m erd_generator ./db/migration ./docs-site/static/img/schema.svg
- name: Build Docusaurus
  working-directory: docs-site
  run: |
    npm ci
    npm run build
```

The separate checkout and `PYTHONPATH` make the module available from the application repository; the generator is not currently distributed as a pip-installable package. Pin its commit and review updates deliberately. For another CI platform, keep the same installation and generation order. ELK runs locally inside D2.

### Reference the diagram

Add this to a Docusaurus Markdown document, for example `docs-site/docs/database.md`:

```markdown
# Database schema

![Database tables and relationships](/img/schema.svg)

[Open the full-size diagram](/img/schema.svg)
```

Use Markdown asset references as above: Docusaurus resolves the file under `static/`, handles a non-root `baseUrl`, and hashes the bundled image URL when its contents change. Avoid hardcoding a root-relative JSX `<img src="/img/schema.svg">`. See the official [static asset reference](https://docusaurus.io/docs/markdown-features/assets#static-assets). The full-size link lets readers open large diagrams separately; the embedded preview does not add pan/zoom controls.

The command creates both `schema.svg` and `schema.d2`; the output directory is created automatically. Treat both as build output and ignore those generated paths in Git. Generate them before local documentation builds too. There is no need for a bot to commit updated images after each CI run.

### Build and publication rules

- Run generation on every documentation CI invocation, before `npm run build`. To run on every repository push/PR, ensure the containing workflow has those triggers without a path filter that excludes SQL changes.
- A detected SQL/configuration failure, missing D2, wrong D2 version or render failure must fail the job. Do not use `continue-on-error`, `|| true`, or an unconditional site deployment. The CLI preserves any previous SVG on failure; it must not be published as a successful regeneration.
- PRs can validate generation and the site build. The main-branch deployment publishes the newly built site. Generating an SVG or uploading a CI artifact alone does not update an already deployed Docusaurus site.
- If generation, build and deployment use separate jobs, pass this run's outputs through artifacts and require the preceding job to succeed. Deploy the site built from the same commit rather than fetching an unrelated latest diagram.
- Keep a previous successful site artifact for rollback. Restoring that artifact restores both the documentation and its diagram; no database rollback is involved.

Before enabling deployment, verify a clean checkout builds successfully, a schema change appears in the SVG, the diagram opens under the deployed `baseUrl`, and a generation failure prevents the site build/deployment. The repository's real-rendering tests cover SVG generation; the consuming site owns its build and deployment checks.

## Repository structure

```text
SQL migrations + optional FK YAML → Schema → schema.d2 → D2 / ELK → schema.svg
```

```text
README.md             # user setup and everyday usage
dev_guide.md          # CLI reference, architecture and contributor workflows
erd_generator/
  __main__.py          # primary python -m entrypoint (D2 default)
  cli.py               # explicit input/output CLI, argument validation and orchestration
  schema.py            # output-independent schema contract
  sql_parser.py        # SQL adapters and per-run loading result
  sql_statements.py    # PostgreSQL tokenization and statement boundaries
  postgres_commands.py # ERD-neutral allowlist and bounded DO block extraction
  postgres_do.py       # whole-block role/permission checks and constant SQL templates
  diagnostics.py       # shared diagnostics (ParseFailure remains re-exported)
  fk_config.py         # YAML relationship loading/resolution
  validation.py        # FK integrity checks and normalized relationships
  layout_config.py     # immutable business overrides and explicit YAML loading
  d2.py                # pure group/region orchestration and D2 source generation
  d2_emit.py           # SQL table, field, connection and container serialization
  d2_business.py       # name families, override resolution and fallback communities
  d2_layout.py         # presentation components and estimated column packing
  d2_grouping.py       # relationship communities, compact layers and shared hubs
  d2_styles.py         # native D2 palette, table and connection presets
  d2_renderer.py       # pinned D2/ELK execution and SVG publication
  test_*.py            # unit tests close to implementation
tests/
  test_cli.py          # subprocess CLI and import-boundary tests
  integration/        # real pinned D2 rendering; missing D2 is a failure
  fixtures/           # explicit small SQL/D2 expectations
scripts/              # reproducible synthetic rendering benchmark
db/migration/         # sample SQL migrations
sample_fk_config.yaml # sample additional relationships
generated/            # ignored generated source, SVG and benchmark output
.github/workflows/    # build/test/lint and real ELK checks
docs/                 # business layout design and validation records
```

SQL dependencies flow from `sql_parser` to `postgres_do` to `postgres_commands`/`sql_statements`; the policy modules do not depend on Schema or rendering. The neutral-block check is pure and runs before any Schema mutation. D2 generation uses `validation`, `d2_business`, `d2_layout` and `d2_grouping` over shared Schema and normalized relationships, then serializes through `d2_emit`. These planners perform no I/O; CLI explicitly loads optional layout YAML before generation. The renderer depends only on shared presentation settings, not on the planners or Schema.

The new explicit loading API is `erd_generator.sql_parser.load_schema_result(path)` returning this run's Schema and diagnostics. The old `load_schema_from_migrations()` / `get_last_parse_failures()` functions remain available for callers using the historical last-run cache. D2 source generation is available as `erd_generator.build_d2(schema, show_types=True, style="clean")` and never mutates its input; `style="classic"` preserves the original D2 output style.

## Development and validation

```bash
python -m pip install -r requirements-dev.txt
python -m compileall -q erd_generator scripts
python -m pytest -q -m 'not integration'
python -m ruff check .
python -m ruff format --check .
python -m pytest -q -m integration
python -m erd_generator ./db/migration ./generated/schema.svg
python scripts/benchmark_rendering.py --tables 50
python scripts/benchmark_rendering.py --tables 200
```

The `not integration` marker runs fast tests without requiring D2. The `integration` marker requires exactly D2 0.7.1 and bundled ELK; missing dependencies fail rather than skip rendering validation. `python -m ruff format .` formats new/rewritten modules while preserving formatting of untouched legacy files.

The benchmark script separately renders deterministic 50- and 200-table synthetic inputs. Each case writes source, SVG and `metrics.json` under `generated/benchmark-N/`, including duration, peak child-process RSS, output bytes and dimensions. These measurements do not predict every production graph's readability or runtime.

CI installs the fixed D2 release with an SHA-256 check and runs build, tests, lint, real rendering and the default command. [Local validation](docs/validation/d2-elk.md) records D2-only checks and remaining limits; [business layout design](docs/plans/d2-business-layout.md) describes layout boundaries and rollback options.

## Supported SQL and limitations

The parser supports a practical PostgreSQL DDL subset: CREATE TABLE, common ALTER column/constraint/rename operations, DROP TABLE/COLUMN/CONSTRAINT/INDEX, CREATE INDEX (including expression/partial metadata) and ALTER INDEX RENAME. The pinned sqlglot DROP representation is handled explicitly, so removed objects no longer remain in the diagram.

The sample plus YAML has **5 tables, 21 columns, 5 FKs and 7 unique/index records** after all migrations. Both the original inline email UNIQUE and the later explicitly named email UNIQUE remain represented.

CHECK/default changes, partitioning, views, enums, routine execution, search_path resolution and all exotic DDL are not fully modeled. Routine definitions and supported setup statements are ignored as described above; unsupported procedural execution and schema mutations yield diagnostics. Some other constructs are still ignored by the existing parser, so zero diagnostics do not prove complete PostgreSQL interpretation. Quoted identifier normalization and index-expression rewrites retain existing parser limitations.

ELK uses hierarchical layout within inferred or configured regions, and independent regions are packed as described above. Automatic grouping combines naming evidence and FK connectivity; it is not a guaranteed business-domain partition. Dense/large diagrams may still contain crossings, extra bends or become wide; there is no fixed-coordinate placement. SVG is intended for browser viewing. PNG/PDF and their browser dependencies are outside the first release.
