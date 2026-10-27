# Mitchell — Claude context

Python library for cloud-ready, lazy access to gravitational-wave analysis
data products (posterior samples, normalising flows, etc.) backed by zarr.

## Repository layout

```
src/mitchell/       Core Python library
bindings/javascript/ TypeScript reader (zarrita); `npm test` in that dir
bindings/julia/     Future: Julia impl of schema using Zarr.jl
bindings/r/         Future: R impl of schema using pizzarr
tests/              pytest test suite
tests/conformance/  Shared fixture store + expected.json read by every binding
.github/workflows/  ci.yml
```

## Multilingual architecture

Mitchell's cross-language contract is the **zarr store schema**, not a shared
compiled core.  Each language implements the schema independently on top of its
own native zarr backend (zarr.js in JavaScript, Zarr.jl in Julia, pizzarr in R).
No language wraps the Python package at runtime.

## Essential commands

```bash
# Install for development
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Lint
ruff check src/ tests/
ruff format src/ tests/

# Type check
mypy src/mitchell
```

## Key constraints

- **Python ≥ 3.11**, zarr ≥ 3.0 (zarr v3 format throughout).
- `src/` layout — package root is `src/mitchell/`.
- Events and analyses are listed through the root `mitchell_index` attribute
  (`docs/schema.md`); zarr consolidated metadata is deliberately *not* used
  (not in the zarr v3 spec).  Anything that changes the tree must update the
  index.
- The zarr store schema is the stability contract; all language bindings must
  conform to it.  Document schema changes clearly.
- `scripts/build_demo_store.py` trims a PESummary metafile into a small store
  (used for the viewer's committed GW150914 demo).
- `mitchell condor-dag` (`src/mitchell/condor.py`) writes an HTCondor DAG that
  converts events in parallel into per-event stores, merged by
  `mitchell combine` (`MitchellStore.merge`).  No HTCondor is available in the
  dev environment: the tests parse the generated files and *emulate* the DAG.
- Dual-licensed MIT.
