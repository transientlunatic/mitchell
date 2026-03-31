# CLI reference

Mitchell ships a command-line tool for working with stores.

## `mitchell from-bilby-h5`

Translate a GWTC bilby HDF5 file into a Mitchell zarr store.

```
Usage: mitchell from-bilby-h5 [OPTIONS] H5_PATH EVENT_NAME ZARR_PATH

  H5_PATH     Path to the source .h5 file.
  EVENT_NAME  Event identifier, e.g. GW150914_095045.
  ZARR_PATH   Destination directory for the zarr store.
```

### Example

```bash
mitchell from-bilby-h5 \
  IGWN-GWTC2p1-v2-GW150914_095045_PEDataRelease_mixed_cosmo.h5 \
  GW150914_095045 \
  GW150914_095045.zarr
```
