# D2 + ELK validation

Date: 2026-09-18. This record covers the D2-only generator after removing the former backend and its compatibility tools. Business-layout measurements and earlier test counts are recorded separately in [business layout validation](d2-business-layout.md).

## Scope

The only generation path is `SQL + optional YAML -> validated Schema -> D2 -> ELK -> SVG`. Both `python -m erd_generator` and Python `erd_generator.main()` use it. A `.d2` output needs no renderer; a `.svg` output also writes same-stem D2 source.

Backend selection and old layout switches are removed, with no aliases or fallback. Invalid options fail before replacing either output. YAML FK resolution always rejects ambiguous tables, wrong qualified names, missing targets and unknown columns. Detected SQL/configuration failures stop generation; render failures retain the prior SVG and report the retained source.

## Environment and checks

A new isolated virtual environment was created from `requirements-dev.txt`, without system site packages. Runtime dependencies are sqlglot 30.18.0 and PyYAML 6.0.3; tests use pytest 9.1.1 and Ruff 0.16.6. Removed graph packages are absent from that environment. Rendering uses D2 0.7.1 with bundled ELK on macOS/Python 3.14.

| Check | Result |
| --- | --- |
| CLI, YAML FK and loader tests | 79 passed after the targeted changes |
| Full suite in the fresh environment | **358 passed in 157.27 s**: 308 fast tests and 50 actual D2/ELK rendering tests |
| `python -m compileall -q erd_generator scripts` | Passed |
| `python -m pip check` | No broken requirements |
| Ruff lint and formatting | Passed |
| Sample CLI with optional FK YAML | D2 and SVG generated successfully; 5 tables, 21 columns and 5 FKs |
| Removed imports and command options | Old modules/export unavailable; old backend options absent from help |
| Documentation links and `git diff --check` | Passed |

The entrypoint regression compares the Python-call and module-command outputs. Removed options are checked for an error and preservation of existing source/SVG. Rendering checks cover real field endpoints, composite FKs, cycles, self references, quoted/Unicode identifiers, both styles, automatic business groups, shared hubs, disconnected packing and deterministic output.

## Sample workflow

```bash
python -m erd_generator ./db/migration ./generated/schema.svg --fk-config ./sample_fk_config.yaml
```

The fictional library migrations plus YAML describe **5 tables, 21 columns, 5 FKs and 7 index/unique records**. Tests assert the final migration semantics, including removal of dropped objects. The golden D2 fixture is regenerated from synthetic SQL and checked with the actual renderer.

## Remaining limits

- Local checks do not establish a remote GitHub Actions or Docusaurus deployment result. CI is configured for Ubuntu/Python 3.11 and 3.14; Windows is not validated here.
- The parser supports a documented PostgreSQL subset and never executes SQL or connects to a database.
- D2 0.7.1 can route self references to table boundaries; explicit field labels remain. Dense graphs can retain crossings and long lines.
- SQL tables keep square corners because rounded quoted table names can produce invalid SVG in the pinned D2 release.
- Source and SVG replacement are separate operations. Publication must require a successful CLI exit.
