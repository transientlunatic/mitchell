"""Mitchell — cloud-ready gravitational-wave analysis data library.

Mitchell uses zarr as its storage backend, providing lazy, chunked, and
optionally remote access to gravitational-wave analysis products such as
posterior sample collections and trained normalising flows.

The mitchell zarr store schema is the cross-language contract: any language
with a zarr implementation (Python, Julia via Zarr.jl, R via pizzarr,
JavaScript via zarr.js) can read a mitchell store without going through this
package.
"""

__version__ = "0.1.0"
