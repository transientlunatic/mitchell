# Mitchell — Claude context

Python library for cloud-ready, lazy access to gravitational-wave analysis
data products (posterior samples, normalising flows, etc.) backed by zarr.

## Repository layout

```
src/mitchell/       Core Python library
bindings/julia/     Future: Julia impl of schema using Zarr.jl
bindings/r/         Future: R impl of schema using pizzarr
tests/              pytest test suite
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

- **Python ≥ 3.10**, zarr ≥ 3.0 (zarr v3 format throughout).
- `src/` layout — package root is `src/mitchell/`.
- The zarr store schema is the stability contract; all language bindings must
  conform to it.  Document schema changes clearly.
- Dual-licensed MIT.
