# Zarr store schema

The zarr store schema is Mitchell's cross-language contract.  Any language
with a zarr implementation can read a Mitchell store without depending on
this Python package.

Current version: **0.2.0**.  Everything below is the contract; the conformance fixture (last section)
is its executable form.

## Store layout

```
{root}/
├── zarr.json                          # mitchell_schema_version + mitchell_index
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

Everything is plain zarr v3.  A reader needs nothing beyond zarr itself to
read any array or group above once it knows the path.

Event and analysis names are used verbatim as zarr node names.  Analysis
names commonly contain a colon (`C01:IMRPhenomXPHM`); percent-encode them
when they appear in a URL.

## The root index

Zarr stores over HTTP or object storage cannot be listed, so a reader cannot
discover which events and analyses exist by walking the tree.  The root
`zarr.json` therefore carries a `mitchell_index` attribute that lists them.
Reading the root `zarr.json` is the only request needed to enumerate a store.

```json
{
  "zarr_format": 3,
  "node_type": "group",
  "attributes": {
    "mitchell_schema_version": "0.2.0",
    "mitchell_index": {
      "events": {
        "GW150914_095045": {
          "C01:IMRPhenomXPHM": {
            "attrs": { "approximant": "IMRPhenomXPHM", "f_low": 20.0 },
            "posterior": ["chi_eff", "mass_1", "mass_2"],
            "n_samples": 64,
            "priors": {
              "samples": ["mass_1"],
              "analytic": { "mass_1": "Uniform(minimum=5, maximum=100)" }
            },
            "psds": { "H1": [32, 2], "L1": [32, 2] },
            "calibration_envelope": { "H1": [300, 7], "L1": [300, 7] },
            "skymap": { "attrs": { "nside": 2, "ordering": "NESTED" }, "shape": [48] },
            "config_file": true
          }
        }
      }
    }
  }
}
```

| Key | Meaning |
|---|---|
| `attrs` | The analysis group's attributes (copy of its `zarr.json`). |
| `posterior` | Sorted parameter names under `posterior/samples/`; `[]` if there is no posterior. |
| `n_samples` | Length of the posterior arrays; omitted without a posterior. |
| `priors` | Omitted if there is no `priors/` group. `samples` lists sampled-prior parameter names; `analytic` copies the attributes of `priors/analytic`. |
| `psds`, `calibration_envelope` | Detector name → array shape; `{}` if absent. |
| `skymap` | Omitted if there is no `skymap/data` array. `attrs` copies the skymap group's attributes, `shape` is the shape of `data`. |
| `config_file` | `true` when a `config_file` group exists.  Its contents are **not** indexed (config files are large); read the group's attributes on demand. |

Rules:

* The index is a summary of the tree, never the source of truth.  Arrays and
  attributes in the tree win if they disagree, and a writer that changes the
  tree must update the index in the same operation.
* Event and analysis keys are sorted, so the index is deterministic.
* Bulk data is never copied into the index.  It still grows with the number
  of parameters and with the analytic priors: measured on the GWTC-2.1
  GW150914 file, a small analysis costs about 1.2-1.6 KB and the complete
  137-parameter one about 18 KB (mostly its analytic prior strings), so that
  event's index is 21 KB.  A catalogue-wide index is therefore megabytes, not
  kilobytes; if that ever matters, the heavy parts (`attrs`, `priors.analytic`)
  are the ones to move out of the index.
* Zarr's *consolidated metadata* is not used.  It is not part of the zarr v3
  specification, so other implementations need not support it, and it embeds
  every array's full codec metadata, which makes it many times larger (about
  218 KB against 21 KB for the same GW150914 event).

## Versioning

The root group carries a `mitchell_schema_version` attribute (semver string).

* While the major version is 0, a **minor** bump may change the layout.
  Readers must check `major.minor` and refuse versions they do not know,
  rather than guess.
* Patch bumps never change the layout.
* The Python and JavaScript readers support 0.1 and 0.2.

### Changes

| Version | Change |
|---|---|
| 0.2.0 | Event/analysis listing moves from zarr consolidated metadata to the root `mitchell_index` attribute.  Consolidated metadata is no longer written and must be ignored. |
| 0.1.0 | Initial layout; stores listed through zarr consolidated metadata. |

### Reading 0.1.0 stores

A 0.1.0 store has no `mitchell_index`.  Its events and analyses are listed
from the `consolidated_metadata` in the root `zarr.json`, which the writer
refreshed after every change.  Readers may keep this path for old stores;
the data layout below the root is identical.

### Upgrading

`mitchell reindex PATH` (or `MitchellStore.rebuild_index()`) scans the tree,
writes `mitchell_index`, drops any stale consolidated metadata and sets the
version to 0.2.0.  Appending an event to a 0.1.0 store with the Python
package performs the same upgrade automatically.  Upgrading needs a store
that can be listed, so run it on local storage and then upload.

## Metadata conventions

Scalar metadata is stored in `zarr.json` `attributes` blocks as plain JSON
values. Byte strings from the original HDF5 files are decoded to UTF-8.
Length-1 arrays are unwrapped to scalars.

## Conformance fixture

`tests/conformance/` holds reference stores and the values every reader must
recover from them (`expected.json`):

* `store.zarr` — the current layout, with a `mitchell_index` and no
  consolidated metadata;
* `store_v0_1.zarr` — the same data in the 0.1.0 layout.

They are generated by `tests/conformance/make_fixture.py` and read by the test
suite of each binding (Python: `tests/test_conformance.py`; JavaScript:
`bindings/javascript/tests/conformance.test.ts`).  Any language binding added
under `bindings/` must pass the same checks.  If you change the schema,
regenerate the fixture, bump the version, add a row to the table above, and
update every binding.
