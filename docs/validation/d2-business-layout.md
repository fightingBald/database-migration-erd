# Business layout validation

Date: 2026-09-18. Local validation uses Python 3.14 and pinned D2 0.7.1 with bundled ELK. This record covers business layout and example sanitization, separately from the earlier [research prototypes](../plans/d2-business-layout.md#实测结果). Later backend-removal checks and current test counts are recorded in [D2-only validation](d2-elk.md).

## Implemented behavior

- The existing `python -m erd_generator SQL_DIR OUTPUT` command infers business families from table-name word prefixes and FK evidence, then emits titles, stable colours and compact regions.
- Optional `--layout-config PATH` overrides membership, titles and colours. Strict configuration failures preserve both existing outputs. Source-only generation works with no D2 executable on PATH.
- Large business regions preserve internal relationship communities. Global FK metadata and qualified field paths survive nested groups; connected groups remain outside cross-cell grids.
- Shared singleton hubs can occupy a central band between neighboring groups. Multiple hubs and uneven group sizes are covered.
- `--grouping none` disables automatic business/community/hub layout. Explicit override groups remain active; removing the override flag as well restores ungrouped behavior.

## Checks

| Check | Result |
| --- | --- |
| `python -m compileall -q erd_generator scripts` | Passed |
| `python -m pytest -q -m 'not integration'` | **315 passed in 12.18 s** after replacing example data |
| `python -m pytest -q -m integration` | **50 passed in 147.94 s**, all using actual D2/ELK rendering |
| `python -m ruff check .` | Passed |
| `python -m ruff format --check .` | Passed, 42 files |
| `git diff --check` | Passed |
| Rollback source comparison | All 16 pre-change `grouping="none"` snapshots remain byte-for-byte identical across connected/mixed inputs, four directions and clean/classic styles |

The new tests cover automatic families without FKs, root/deep prefixes, technical/numeric names, same names in different namespaces, Unicode, naming/FK conflicts, unrelated-table stability, deterministic ordering, exact and wildcard overrides, duplicate YAML keys, invalid values, zero matches, overlapping groups, CLI failures and artifact preservation.

Rendering checks cover 24 isolated tables with different heights, 100 automatically grouped tables, cross-domain composite keys and cycles in all four directions and both visual styles, quoted/reserved names, literal substitutions, self references, multiple shared hubs, uneven domain sizes, groups spanning separate FK components and two large named regions with four inner communities. SVG assertions check table coverage, table/region overlap, title space, natural row dimensions where applicable, connector counts, actual arrow direction and field-row endpoints.

An early region-geometry assertion was corrected after inspecting D2's nested `<g class="shape"><rect ...>` container representation. The checks now inspect actual region rectangles; they were not removed. A fixed finite automatic palette was also replaced after a regression showed three unrelated business families receiving the same colour; automatic colours now derive their hue from stable identifiers, while explicit named colours remain available.

## Complete CLI smoke and visual inspection

After example sanitization, the ordinary CLI rendered a new synthetic migration directory containing **41 tables, 192 columns and 111 FKs**, with no layout YAML. The input renames the four interleaved domains from `tests/fixtures/related_tables.sql` to Books, Loans, Members and Branches families in `demo_library`, then adds one shared directory table referenced by every other table. These measurements replace the earlier smoke results because label lengths affect geometry.

| Measurement | Result |
| --- | --- |
| Automatically named regions | 4, with a separate shared directory table |
| SVG width × height | 5050 × 4080 |
| Longer side / shorter side | 1.238 |
| Field connections | 111, all retained and checked |
| Longest routed-length estimate | 4477.5 |
| Total routed-length estimate | 161610.0 |
| Logged D2 rendering time | 3.423 s on this machine |

Route lengths are Manhattan-distance estimates through SVG route points/control points, not exact Bézier arc lengths. Full-image inspection confirmed distinguishable business regions and a shared table between the surrounding domains. Generated source, SVG, inspection PNG and measured JSON are temporary local artifacts; no demonstration files or external-site changes were added to the runtime workflow.

The checked-in `db/migration` sample and `sample_fk_config.yaml` also render successfully: **5 fictional library tables, 21 columns and 5 FKs**. The golden D2 fixture and local generated SVG were rebuilt from synthetic SQL; obsolete parser logs and local presentation artifacts were removed. Working-tree scans cover source, docs, fixtures, filenames and generated output, excluding Git metadata and dependency/cache directories. Git-history cleanup is a separate operation; this validation does not claim old commits were rewritten.

These synthetic measurements do not establish a universal readability or performance guarantee. Dense graphs can retain long edges and crossings; D2 may enlarge highly connected SQL tables. Self references retain the existing explicit field labels and D2 0.7.1 table-boundary routing limitation. Acceptance uses synthetic schemas only; remote GitHub Actions/Docusaurus deployment was not run in this task.
