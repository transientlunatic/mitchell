"""Sphinx configuration for Mitchell docs."""

import os
from importlib.metadata import version as _version
from pathlib import Path

project = "Mitchell"
copyright = "2026, The Mitchell Authors"
author = "The Mitchell Authors"
release = _version("mitchell")

extensions = [
    "autoapi.extension",
    "myst_parser",
    "sphinxcontrib.katex",
    "kentigern",
    "sphinx.ext.intersphinx",
    "sphinx_js",
]

# -- Intersphinx -------------------------------------------------------------
intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "zarr": ("https://zarr.readthedocs.io/en/stable", None),
    "arviz": ("https://python.arviz.org/en/stable", None),
}

# Suppress cross-reference warnings for types whose inventories may be
# incomplete or missing (e.g. zarr internal sub-modules, arviz aliases).
nitpick_ignore = [
    ("py:class", "zarr.Group"),
    ("py:class", "zarr.attrs.Attributes"),
    ("py:class", "zarr.storage.StoreLike"),
    ("py:func", "zarr.open_group"),
    ("py:class", "arviz.InferenceData"),
    ("py:class", "os.PathLike"),
    # sphinx-js generates internal module cross-references that it cannot
    # resolve itself when TypeDoc module names don't map 1-to-1 to pages.
    ("js:mod", "store"),
    ("js:mod", "types"),
]

# -- AutoAPI (Python) --------------------------------------------------------
autoapi_dirs = ["../src/mitchell"]
autoapi_options = [
    "members",
    "undoc-members",
    "show-inheritance",
    "show-module-summary",
]
autoapi_member_order = "groupwise"
autoapi_add_toctree_entry = True

# -- sphinx-js (TypeScript / JavaScript) -------------------------------------
js_language = "typescript"
js_source_path = "../bindings/javascript/src"
jsdoc_config_path = "typedoc.json"

# Point sphinx-js to the typedoc binary installed in the JS binding's
# node_modules so that no global npm install is required.
os.environ.setdefault(
    "SPHINX_JS_NODE_MODULES",
    str(Path(__file__).parent.parent / "bindings" / "javascript" / "node_modules"),
)

# Ensure a Node.js >= 18 binary is on PATH for sphinx-js to use when
# spawning typedoc.  In CI the correct node is already on PATH; locally
# we look for an nvm-managed version if the system node is too old.
# NOTE: docs must be built from the repository root so that the relative
# paths in typedoc.json (e.g. ``../bindings/javascript/tsconfig.json``)
# resolve correctly.
def _node_major() -> int:
    import subprocess
    try:
        out = subprocess.check_output(["node", "--version"], text=True).strip()
        return int(out.lstrip("v").split(".")[0])
    except Exception:
        return 0

def _nvm_version_key(p: Path) -> tuple:
    import re
    m = re.match(r"v(\d+)\.(\d+)\.(\d+)", p.name)
    return tuple(int(x) for x in m.groups()) if m else (0, 0, 0)

if _node_major() < 18:
    nvm_versions = Path.home() / ".nvm" / "versions" / "node"
    if nvm_versions.is_dir():
        for candidate in sorted(nvm_versions.iterdir(), key=_nvm_version_key, reverse=True):
            _bin = candidate / "bin"
            if (_bin / "node").is_file():
                os.environ["PATH"] = str(_bin) + os.pathsep + os.environ.get("PATH", "")
                break

# -- MyST --------------------------------------------------------------------
myst_enable_extensions = ["dollarmath", "amsmath"]

# -- HTML theme --------------------------------------------------------------
html_theme = "kentigern"
html_title = "Mitchell"

# -- Source suffixes ---------------------------------------------------------
source_suffix = {
    ".rst": "restructuredtext",
    ".md": "myst",
}
