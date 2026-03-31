"""Sphinx configuration for Mitchell docs."""

from importlib.metadata import version as _version

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
]

# -- AutoAPI -----------------------------------------------------------------
autoapi_dirs = ["../src/mitchell"]
autoapi_options = [
    "members",
    "undoc-members",
    "show-inheritance",
    "show-module-summary",
]
autoapi_member_order = "groupwise"
autoapi_add_toctree_entry = True

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
