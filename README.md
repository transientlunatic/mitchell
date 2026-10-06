# mitchell
Mitchell is a next-generation gravitational-wave data library which uses zarr under-the-hood to provide cloud-ready and parallelisable access to gravitational wave analysis data.

Convert PESummary HDF5 files with `mitchell from-pesummary`, or build a
store straight from every published GWTC event with
`mitchell from-gwtc` (requires the optional `gwresults` dependency:
`pip install 'mitchell[gwtc]'`). See `CLAUDE.md` for details.
