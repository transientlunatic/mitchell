"""Mitchell command-line interface."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import click

from mitchell import condor
from mitchell.store import MitchellStore, Mode, OnConflict, analysis_groups

_EVENT_NAME_RE = re.compile(r"GW\d{6}_\d{6}")


def _infer_event_name(path: Path) -> str:
    """Extract the GW event name from a PESummary filename stem."""
    m = _EVENT_NAME_RE.search(path.stem)
    if m is None:
        raise click.BadParameter(
            f"Cannot infer event name from filename {path.name!r}. "
            "Use --event-name to provide it explicitly.",
            param_hint="--event-name",
        )
    return m.group()


@click.group()
@click.version_option(package_name="mitchell")
def cli() -> None:
    """Mitchell — gravitational-wave analysis data tools."""


@cli.command("from-pesummary")
@click.argument("h5_path", type=click.Path(exists=True))
@click.argument("zarr_path", type=click.Path())
@click.option(
    "--event-name",
    default=None,
    metavar="NAME",
    help=(
        "Event identifier, e.g. GW150914_095045.  Inferred from the filename "
        "when not given.  Not valid when H5_PATH is a directory."
    ),
)
@click.option(
    "--overwrite",
    is_flag=True,
    default=False,
    help="Overwrite an existing zarr store instead of appending to it.",
)
def from_pesummary(
    h5_path: str, zarr_path: str, event_name: str | None, overwrite: bool
) -> None:
    """Translate one or more GWTC PESummary HDF5 files into a Mitchell zarr store.

    \b
    H5_PATH   Path to a .h5 file, or a directory of .h5 files.
    ZARR_PATH Destination zarr store directory (created if absent).

    When H5_PATH is a directory every ``*.h5`` file within it is converted and
    appended to the same zarr store.  Event names are inferred from filenames
    using the GWTC naming convention (GW{YYMMDD}_{HHMMSS}).

    Use --event-name to override the inferred name for a single file.

    By default events are appended to an existing store.  Pass --overwrite to
    create a fresh store, discarding previous contents.
    """
    source = Path(h5_path)

    if source.is_dir():
        if event_name is not None:
            raise click.UsageError(
                "--event-name cannot be used when H5_PATH is a directory."
            )
        files = sorted(source.glob("*.h5"))
        if not files:
            raise click.ClickException(f"No .h5 files found in {source}")
        _run_batch(files, zarr_path, overwrite)
    else:
        name = event_name or _infer_event_name(source)
        _run_single(source, name, zarr_path, "w" if overwrite else "a")


def _run_single(h5_path: Path, event_name: str, zarr_path: str, mode: Mode) -> None:
    import h5py as h5

    click.echo(f"Translating {h5_path} → {zarr_path} (event: {event_name})")
    with h5.File(h5_path, "r") as f:
        analyses = list(analysis_groups(f))
    click.echo(f"  {len(analyses)} analysis group(s): {', '.join(analyses)}")
    MitchellStore.from_pesummary_h5(h5_path, event_name, zarr_path, mode=mode)
    click.echo("Done.")


def _run_batch(files: list[Path], zarr_path: str, overwrite: bool) -> None:
    click.echo(f"Converting {len(files)} file(s) → {zarr_path}")
    for i, h5_path in enumerate(files):
        event_name = _infer_event_name(h5_path)
        mode: Mode = "w" if (overwrite and i == 0) else "a"
        _run_single(h5_path, event_name, zarr_path, mode)


@cli.command("combine")
@click.argument("zarr_path", type=click.Path())
@click.argument("parts", nargs=-1, type=click.Path(exists=True))
@click.option(
    "--parts-dir",
    type=click.Path(exists=True, file_okay=False),
    default=None,
    help="A directory whose *.zarr subdirectories are the parts to merge.",
)
@click.option(
    "--on-conflict",
    type=click.Choice(["skip", "replace", "error"]),
    default="skip",
    show_default=True,
    help="What to do with an event already in ZARR_PATH.",
)
@click.option(
    "--move/--copy",
    default=False,
    help="Move events out of the parts (no second copy of the data; a part left "
    "empty is removed) instead of copying them.",
)
def combine(
    zarr_path: str,
    parts: tuple[str, ...],
    parts_dir: str | None,
    on_conflict: OnConflict,
    move: bool,
) -> None:
    """Merge Mitchell stores (PARTS) into the catalogue ZARR_PATH.

    Parts are typically single-event stores built independently, for example
    one per job of a Condor DAG (see ``mitchell condor-dag``).  The catalogue
    is created if absent and its index is written once, at the end.  Re-running
    is safe: events already present are skipped unless --on-conflict says
    otherwise.  Local filesystem paths only.
    """
    paths = [Path(p) for p in parts]
    if parts_dir is not None:
        paths += sorted(p for p in Path(parts_dir).glob("*.zarr") if p.is_dir())
    if not paths:
        raise click.UsageError("No parts given (list them, or use --parts-dir).")

    store = MitchellStore.open(zarr_path, mode="a")
    try:
        result = store.merge(paths, on_conflict=on_conflict, move=move)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        f"Added {len(result.added)} event(s), replaced {len(result.replaced)}, "
        f"skipped {len(result.skipped)} → {zarr_path} "
        f"({len(store._event_names())} total)."
    )


@cli.command("condor-dag")
@click.argument("dag_dir", type=click.Path())
@click.argument("zarr_path", type=click.Path())
@click.option(
    "--h5-dir",
    type=click.Path(exists=True, file_okay=False),
    default=None,
    help="Convert the PESummary *.h5 files in this directory.",
)
@click.option(
    "--gwtc",
    is_flag=True,
    default=False,
    help="Fetch published GWTC events via gwresults (needs network access on the "
    "workers).  Give exactly one of --h5-dir and --gwtc.",
)
@click.option(
    "--gwtc-catalogue",
    "gwtc_catalogues",
    multiple=True,
    metavar="NAME",
    help="With --gwtc, restrict to a catalogue (e.g. GWTC-2.1). Repeatable.",
)
@click.option(
    "--event",
    "events",
    multiple=True,
    metavar="NAME",
    help="Only these events. Repeatable.",
)
@click.option("--limit", type=int, default=None, help="At most N events.")
@click.option(
    "--skip-existing/--no-skip-existing",
    default=True,
    show_default=True,
    help="Leave out events already in ZARR_PATH, so the DAG only adds what is new.",
)
@click.option(
    "--retries",
    type=int,
    default=condor.DEFAULT_RETRIES,
    show_default=True,
    help="Times DAGMan retries a failed node.",
)
@click.option(
    "--request-memory",
    default=condor.DEFAULT_MEMORY,
    show_default=True,
    help="Memory per conversion job (~0.3 GB measured for GW150914).",
)
@click.option(
    "--request-disk",
    default=condor.DEFAULT_DISK,
    show_default=True,
    help="Scratch disk per conversion job.",
)
@click.option(
    "--max-jobs",
    type=int,
    default=None,
    help="Run at most N conversion jobs at once.  Default: "
    f"{condor.DEFAULT_MAX_DOWNLOADS} with --gwtc (downloads), unlimited otherwise.",
)
@click.option("--accounting-group", default=None, help="Condor accounting group.")
@click.option(
    "--accounting-group-user", default=None, help="Condor accounting group user."
)
@click.option(
    "--container-image",
    default=None,
    help="Run the conversion jobs in this container image (then --mitchell is "
    "the command name inside it).",
)
@click.option(
    "--mitchell",
    "mitchell_command",
    default=None,
    help="The mitchell executable the jobs run.  Default: the one on PATH, whose "
    "environment must be visible to the workers (a shared filesystem).",
)
@click.option(
    "--keep-parts",
    is_flag=True,
    default=False,
    help="Copy the parts into the catalogue instead of moving them, leaving "
    "parts/ intact (twice the disk).",
)
def condor_dag(
    dag_dir: str,
    zarr_path: str,
    h5_dir: str | None,
    gwtc: bool,
    gwtc_catalogues: tuple[str, ...],
    events: tuple[str, ...],
    limit: int | None,
    skip_existing: bool,
    retries: int,
    request_memory: str,
    request_disk: str,
    max_jobs: int | None,
    accounting_group: str | None,
    accounting_group_user: str | None,
    container_image: str | None,
    mitchell_command: str | None,
    keep_parts: bool,
) -> None:
    """Write an HTCondor DAG in DAG_DIR that builds the catalogue ZARR_PATH.

    One job per event converts it into a small store of its own, in parallel;
    a final job merges them with ``mitchell combine``.  Then:

    \b
        cd DAG_DIR && condor_submit_dag catalogue.dag

    If the DAG stops part-way, submit it again: DAGMan resumes and reruns only
    what did not finish.  With --skip-existing (the default) a later DAG adds
    only the events ZARR_PATH lacks.
    """
    if (h5_dir is None) == (not gwtc):
        raise click.UsageError("Give exactly one of --h5-dir and --gwtc.")
    if gwtc_catalogues and not gwtc:
        raise click.UsageError("--gwtc-catalogue needs --gwtc.")

    wanted = set(events)
    nodes: list[condor.Node] = []
    if h5_dir is not None:
        unnamed: list[str] = []
        for path in sorted(Path(h5_dir).glob("*.h5")):
            try:
                name = _infer_event_name(path)
            except click.BadParameter:
                unnamed.append(path.name)
                continue
            if not wanted or name in wanted:
                nodes.append(condor.Node(name, path))
        if unnamed:
            raise click.ClickException(
                "Cannot infer an event name (GW{YYMMDD}_{HHMMSS}) from: "
                + ", ".join(unnamed)
            )
        if not nodes and not list(Path(h5_dir).glob("*.h5")):
            raise click.ClickException(f"No .h5 files found in {h5_dir}")
    else:
        try:
            import gwresults  # noqa: F401
        except ImportError as exc:
            raise click.ClickException(
                "gwresults is required for --gwtc: pip install 'mitchell[gwtc]'"
            ) from exc
        from mitchell.gwtc import iter_gwtc_events

        names = sorted(wanted) or iter_gwtc_events(list(gwtc_catalogues) or None)
        nodes = [condor.Node(name) for name in names]

    if skip_existing and Path(zarr_path).exists():
        present = MitchellStore.open(zarr_path, mode="r")
        nodes = [n for n in nodes if n.event not in present]
    if limit is not None:
        nodes = nodes[:limit]
    if not nodes:
        raise click.ClickException(
            "Nothing to do: no events selected (or all are already in the catalogue)."
        )

    executable = mitchell_command or shutil.which("mitchell")
    if executable is None:
        raise click.ClickException(
            "Cannot find the mitchell executable on PATH; pass --mitchell."
        )
    options = condor.Options(
        catalogue=Path(zarr_path).resolve(),
        mitchell=executable,
        source="gwtc" if gwtc else "h5",
        retries=retries,
        request_memory=request_memory,
        request_disk=request_disk,
        max_jobs=max_jobs,
        accounting_group=accounting_group,
        accounting_group_user=accounting_group_user,
        container_image=container_image,
        keep_parts=keep_parts,
    )
    try:
        dag = condor.write_dag(Path(dag_dir), nodes, options)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        f"Wrote a DAG of {len(nodes)} event(s) to {dag}\n"
        f"Submit it with:  cd {dag.parent} && condor_submit_dag {dag.name}"
    )


@cli.command("reindex")
@click.argument("zarr_path", type=click.Path(exists=True))
def reindex(zarr_path: str) -> None:
    """Rebuild the event index of ZARR_PATH, upgrading it to the current schema.

    Use this on a store written before schema 0.2.0 (which relied on zarr
    consolidated metadata) or one whose index is out of date.  The store must
    be on a filesystem that can list directories.
    """
    store = MitchellStore.open(zarr_path, mode="r+")
    previous = store.schema_version
    store.rebuild_index()
    click.echo(
        f"Indexed {len(store)} event(s) in {zarr_path} "
        f"(schema {previous} -> {store.schema_version})."
    )


@cli.command("from-gwtc")
@click.argument("zarr_path", type=click.Path())
@click.option(
    "--catalogue",
    "catalogues",
    multiple=True,
    metavar="NAME",
    help="Restrict to one or more catalogues (e.g. GWTC-2.1). Repeatable. "
    "Defaults to every catalogue in the gwresults registry.",
)
@click.option(
    "--event",
    "events",
    multiple=True,
    metavar="NAME",
    help="Restrict to specific event name(s). Repeatable. Overrides --catalogue.",
)
@click.option(
    "--limit",
    type=int,
    default=None,
    help="Process at most N events (useful for smoke-testing).",
)
@click.option(
    "--keep-cache",
    is_flag=True,
    default=False,
    help="Keep each downloaded HDF5 in the gwresults cache instead of "
    "deleting it right after conversion.",
)
def from_gwtc(
    zarr_path: str,
    catalogues: tuple[str, ...],
    events: tuple[str, ...],
    limit: int | None,
    keep_cache: bool,
) -> None:
    """Fetch published GWTC events via gwresults and convert them into ZARR_PATH.

    Requires the optional 'gwresults' package (``pip install
    'mitchell[gwtc]'``). Streams one event at a time — download, convert,
    delete the HDF5 — so local disk use stays small even across a full
    catalogue. Already-converted events are skipped, so an interrupted run
    can simply be re-invoked.

    Every event is attempted even if some fail, but the exit status is 1 if
    any did, so a scheduler can tell and retry.
    """
    try:
        import gwresults  # noqa: F401
    except ImportError as exc:
        raise click.ClickException(
            "gwresults is required for this command: pip install gwresults"
        ) from exc

    from mitchell.gwtc import build_from_gwtc

    converted = skipped = failed = 0
    for result in build_from_gwtc(
        zarr_path,
        catalogues=list(catalogues) or None,
        events=list(events) or None,
        limit=limit,
        keep_cache=keep_cache,
    ):
        click.echo(f"[{result.status}] {result.event_name} {result.detail}".rstrip())
        if result.status == "converted":
            converted += 1
        elif result.status == "skipped":
            skipped += 1
        else:
            failed += 1

    click.echo(f"Done: {converted} converted, {skipped} skipped, {failed} failed.")
    if failed:
        raise click.ClickException(f"{failed} event(s) failed")
