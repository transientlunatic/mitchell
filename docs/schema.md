# Zarr store schema

The zarr store schema is Mitchell's cross-language contract.  Any language
with a zarr implementation can read a Mitchell store without depending on
this Python package.

## Store layout

```
{root}/
├── zarr.json                          # mitchell_schema_version attribute
└── events/
    └── {event_name}/                  # e.g. GW150914_095045
        └── {analysis_name}/           # e.g. C01:IMRPhenomXPHM
            ├── zarr.json              # approximant, f_low, f_ref, … attributes
            ├── posterior/
            │   └── samples/
            │       ├── mass_1         # (N,) float64
            │       ├── mass_2         # (N,) float64
            │       └── …
            ├── priors/
            │   ├── samples/
            │   │   ├── mass_1         # (N,) float64
            │   │   └── …
            │   └── analytic/
            │       └── zarr.json      # {param: "Prior string"} attributes
            ├── psds/
            │   ├── H1                 # (N, 2) float64  [frequency, ASD]
            │   └── L1
            ├── calibration_envelope/
            │   ├── H1                 # (300, 7) float64
            │   └── L1
            ├── skymap/
            │   ├── zarr.json          # HEALPix metadata attributes
            │   └── data               # (3145728,) float64
            └── config_file/
                └── zarr.json          # {key: value} INI config attributes
```

## Versioning

The root group carries a `mitchell_schema_version` attribute (semver string).
Readers should check this to determine compatibility.

## Metadata conventions

Scalar metadata is stored in `zarr.json` `attributes` blocks as plain JSON
values. Byte strings from the original HDF5 files are decoded to UTF-8.
Length-1 arrays are unwrapped to scalars.
