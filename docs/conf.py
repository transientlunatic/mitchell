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
