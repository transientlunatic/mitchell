# Building a catalogue with HTCondor

Converting a catalogue event by event is slow.  Measured on the GWTC-2.1
GW150914 file (134 MB), the conversion itself takes about 13 s and 270 MB of
memory; what takes the time is fetching and converting hundreds of events one
after another (the GWTC-2.1 release alone is about 22 GB).  The events are
independent, so `mitchell condor-dag` writes an HTCondor DAG that does them in
parallel:

```
convert_GW150914_095045 ┐
convert_GW151012_095443 ├─▶ combine ─▶ catalogue.zarr
convert_...             ┘
```

Each `convert_*` job builds a small store of its own, `parts/<event>.zarr`.
Separate stores mean concurrent jobs never rewrite the same root index, and
DAGMan can retry one failed event without touching the rest.  The final
`combine` job runs `mitchell combine`, which moves the parts into the
catalogue and writes the catalogue's index once.

How much faster this is depends on your pool and, when fetching from Zenodo,
on bandwidth; I have not measured it on a real pool.

## Quick start

From a directory of PESummary files (`GW{YYMMDD}_{HHMMSS}` in each file name):

```bash
mitchell condor-dag dag/ catalogue.zarr --h5-dir /path/to/metafiles
cd dag && condor_submit_dag catalogue.dag
```

Or fetch the published events through `gwresults` (needs
`pip install 'mitchell[gwtc]'`, and network access from the workers):

```bash
mitchell condor-dag dag/ catalogue.zarr --gwtc --gwtc-catalogue GWTC-2.1
cd dag && condor_submit_dag catalogue.dag
```

The command prints how many events it found and the `condor_submit_dag` line.
`--event NAME` (repeatable) and `--limit N` narrow the selection; try
`--limit 2` first.

On a LIGO cluster you will need an accounting group:

```bash
mitchell condor-dag dag/ catalogue.zarr --h5-dir metafiles \
    --accounting-group ligo.dev.o4.cbc --accounting-group-user albert.einstein
```

## What is written

| File | Purpose |
|---|---|
| `catalogue.dag` | One `convert_<event>` node per event (with `RETRY` and a `convert` category), and a `combine` node that waits for all of them. |
| `convert_h5.sub` or `convert_gwtc.sub` | The submit description every conversion node shares; DAGMan fills in `$(event)`, `$(part)` and, for files, `$(h5)` and `$(h5file)`. |
| `combine.sub` | The merge job. |
| `run_mitchell.sh` | The executable: a wrapper that runs `mitchell` with its download cache redirected to the job's scratch directory (a worker's home directory is often missing or read-only). |
| `parts/`, `logs/` | Where the per-event stores come back to, and the job output and logs. Condor will not create these, so they are made for you. |

`catalogue.dag.status` is written while the DAG runs.

## Failures and resuming

Each conversion is retried up to `--retries` times (default 3).  The commands
the jobs run exit non-zero when an event fails (`mitchell from-gwtc` does so
after trying every event it was given), which is how DAGMan knows to retry.

Two details keep a failure a *failure* rather than a stall or a mess:

- Condor puts a job on **hold**, not into failure, when a file listed in
  `transfer_output_files` is missing, and a held job stalls the DAG.  The most
  likely cause is `mitchell` not being visible on a worker, so nothing creates
  `part.zarr`.  The wrapper script therefore creates it up front; the job then
  fails normally and DAGMan retries it.
- Every attempt returns its store to `parts/<event>.zarr`, and a failed attempt
  may leave a partial one.  A DAGMan `SCRIPT PRE` removes it before each try.

If a node still fails, DAGMan stops after finishing what it can and writes a
rescue DAG.  Submit `catalogue.dag` again: DAGMan picks up the rescue file and
reruns only what did not finish.  The `combine` node does not start until every
conversion has succeeded.

To add events to an existing catalogue later, run `condor-dag` again with the
same arguments.  `--skip-existing` (the default) leaves out events already in
`catalogue.zarr`, so the new DAG covers only what is missing.

## Your pool

- **The `mitchell` executable.**  By default the jobs run the `mitchell` found on
  your `PATH`, by absolute path, so its Python environment must be visible to the
  workers (a shared filesystem, as on most LIGO clusters).  Use `--mitchell PATH`
  to point at another one.
- **Containers.**  `--container-image IMAGE` adds `universe = container` and
  `container_image`; then pass `--mitchell mitchell` (the command name inside the
  image).  I have not run this on a pool that uses it.
- **Network.**  `--gwtc` downloads from Zenodo on the workers.  If they have no
  outbound access, download the files first and use `--h5-dir`.  Downloads are
  limited to 8 at a time by default (`--max-jobs` changes that).
- **Resources.**  Each job asks for 2 GB of memory and 3 GB of disk
  (`--request-memory`, `--request-disk`), several times the measured need.
  File transfer is on: the per-event store comes back through Condor's file
  transfer, so no shared filesystem is needed for the data itself.
- **The `combine` node** runs in the local universe, on the submit host, because
  it only moves files within the directory the parts were returned to.  If your
  pool does not allow local-universe jobs, let the conversions finish and run
  `mitchell combine catalogue.zarr --parts-dir dag/parts --move` yourself.
- **Disk.**  `combine` moves the parts, so the data is not held twice; with
  `--keep-parts` it copies them instead and `parts/` stays intact.

## Merging by hand

`mitchell combine` is useful on its own for stores built any other way:

```bash
mitchell combine catalogue.zarr part1.zarr part2.zarr
mitchell combine catalogue.zarr --parts-dir parts/ --move
```

It creates the catalogue if needed, skips events already present (so it is safe
to re-run; `--on-conflict replace|error` change that), and writes the index once.
Paths must be on the local filesystem.

## What has and has not been tested

HTCondor is not installed in the development environment, so none of this has
run on a real pool.  The tests (`tests/test_condor.py`) check that:

- the DAG parses back with the expected nodes, variables, retries, categories,
  throttle and dependency edges;
- every submit description passes HTCondor's own parser (`htcondor2.Submit`),
  which checks syntax but not whether a pool accepts the commands;
- an **emulated run**, which reads the generated files back, expands the macros
  as DAGMan would, runs each node through the generated wrapper script in its own
  scratch directory, applies the file transfers by hand, and then merges, builds
  a catalogue identical (index and data) to a sequential conversion.

`condor_submit_dag` itself has not been run against the DAG file.  Try a small
run (`--limit 2`) before a full catalogue.
