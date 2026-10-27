# CLI reference

Mitchell ships a command-line tool for working with stores.

## `mitchell from-pesummary`

Translate one or more GWTC PESummary HDF5 files into a Mitchell zarr store.

```
Usage: mitchell from-pesummary [OPTIONS] H5_PATH ZARR_PATH

  H5_PATH    A .h5 file, or a directory of .h5 files.
  ZARR_PATH  Destination zarr store directory (created if absent).

Options:
  --event-name NAME  Event identifier, e.g. GW150914_095045.  Inferred from
                     the filename when not given.  Not valid for a directory.
  --overwrite        Replace an existing store instead of appending to it.
```

Each event is appended to the store and the root `mitchell_index` is updated
(see [the schema](schema.md)).

```bash
mitchell from-pesummary \
  IGWN-GWTC2p1-v2-GW150914_095045_PEDataRelease_mixed_cosmo.h5 \
  catalogue.zarr
```

## `mitchell from-gwtc`

Fetch published GWTC events through `gwresults` and convert them, one event at
a time, into a store (`pip install 'mitchell[gwtc]'`).  Already-converted events
are skipped, so an interrupted run can be re-run.

```bash
mitchell from-gwtc catalogue.zarr --catalogue GWTC-2.1 --limit 5
```

## `mitchell reindex`

Rebuild the event index of an existing store and upgrade it to the current
schema.  Use it on a store written before schema 0.2.0 (which listed its
contents through zarr consolidated metadata), or one whose index is out of
date.  The store must be on a filesystem that can list directories.

```
Usage: mitchell reindex ZARR_PATH
```

```bash
mitchell reindex old-catalogue.zarr
# Indexed 42 event(s) in old-catalogue.zarr (schema 0.1.0 -> 0.2.0).
```

## `mitchell combine`

Merge Mitchell stores into a catalogue (for example the per-event stores built by
a Condor DAG).

```
Usage: mitchell combine [OPTIONS] ZARR_PATH [PARTS]...

Options:
  --parts-dir DIRECTORY           A directory whose *.zarr subdirectories are
                                  the parts to merge.
  --on-conflict [skip|replace|error]
                                  What to do with an event already in
                                  ZARR_PATH.  [default: skip]
  --move / --copy                 Move events out of the parts instead of
                                  copying them.
```

## `mitchell condor-dag`

Write an HTCondor DAG that builds a catalogue in parallel.  See
[Building a catalogue with HTCondor](condor.md) for the full description.

```bash
mitchell condor-dag dag/ catalogue.zarr --h5-dir /path/to/metafiles
mitchell condor-dag dag/ catalogue.zarr --gwtc --gwtc-catalogue GWTC-2.1
```

## Exit status

`mitchell from-gwtc` tries every event it is given, then exits with status 1 if
any failed, so that a scheduler can detect and retry the failure.
