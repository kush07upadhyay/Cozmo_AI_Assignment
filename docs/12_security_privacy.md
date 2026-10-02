# 12 — Security & Privacy

## Data sensitivity

Room scans and damage photos are imagery of someone's home: floor plans, interior layout, and
close-up photos of their property's condition. This is personal/sensitive data even though it
is not a standard regulated category (PII/PHI/payment data) — it reveals where someone lives,
their home's layout (a physical-security-relevant fact), and its condition/value.

## Local-only processing (constraint compliance)

The spec requires "everything runs without calling your infrastructure." Verified, not assumed:

```
grep -rn "requests\.|urllib|socket\.|http\.client|aiohttp|urlopen" cozmoscan/
```

returns zero matches — there is no network-call code anywhere in the pipeline package. Every
stage (capture loading, geometry fitting, damage detection, rendering, schema validation) reads
and writes local files only (`pathlib.Path`), with no outbound HTTP/socket calls, no telemetry,
and no API keys anywhere in the codebase or config.

## Storage / retention recommendations (not implemented, since this is a CLI pipeline, not a
hosted service — documented for whoever would operationalize this)

- Treat `out/` (and any customer-equivalent output directory) as containing sensitive imagery;
  it is excluded from version control (`.gitignore`) for exactly this reason, independent of its
  large binary size.
- If this pipeline were deployed as a service rather than run locally, captures/outputs should be
  encrypted at rest, access-scoped per customer, and deleted on an explicit retention schedule —
  none of this applies to the current local-CLI deliverable, but is the natural next step.

## OWASP-relevant notes on the pipeline code itself

- **Injection**: all file I/O uses `pathlib.Path` joins and library-native readers (`PIL`,
  `opencv`, `json`, `numpy`), never shell-outs or string-built commands — no shell/SQL/command
  injection surface exists anywhere in `cozmoscan/`.
- **Deserialization**: inputs are JSON (via the standard `json` module, not `pickle` or `eval`)
  or image/video binary formats read through established libraries (Pillow, OpenCV, imageio) —
  no arbitrary code execution on attacker-controlled input is possible via the pipeline's own
  parsing paths.
- **Schema validation on every output**: both output JSON shapes (`capture_output`,
  `property_output`) are validated against a published draft-07 JSON Schema
  (`jsonschema.validate`) before being written, catching malformed/incomplete output before it
  reaches a consumer.
- **CLI argument handling**: `cozmoscan/cli.py` uses `argparse` exclusively — no `eval`/`exec` of
  user input, no shell invocation of user-supplied strings.
- **Dependency supply chain**: every dependency in [requirements.txt](../requirements.txt) is
  version-pinned (`==`), not range-pinned, for reproducible, auditable builds.
- **Error handling at the CLI boundary**: `cozmoscan/cli.py::main()` catches exceptions at the
  top level and reports them via `stderr` + a non-zero exit code rather than leaking a raw
  traceback or silently swallowing failures (see memory note on silent `try/except` anti-patterns
  — this pipeline does the opposite: validate explicitly, fail loudly, exit non-zero).
