"""Mitchell command-line interface."""

from __future__ import annotations

import re
from pathlib import Path

import click

from mitchell.store import MitchellStore

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

    When H5_PATH is a directory every *.h5 file within it is converted and
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


def _run_single(h5_path: Path, event_name: str, zarr_path: str, mode: str) -> None:
    import h5py as h5

    click.echo(f"Translating {h5_path} → {zarr_path} (event: {event_name})")
    with h5.File(h5_path, "r") as f:
        analyses = list(f.keys())
    click.echo(f"  {len(analyses)} analysis group(s): {', '.join(analyses)}")
    MitchellStore.from_pesummary_h5(h5_path, event_name, zarr_path, mode=mode)
    click.echo("Done.")


def _run_batch(files: list[Path], zarr_path: str, overwrite: bool) -> None:
    click.echo(f"Converting {len(files)} file(s) → {zarr_path}")
    for i, h5_path in enumerate(files):
        event_name = _infer_event_name(h5_path)
        mode = "w" if (overwrite and i == 0) else "a"
        _run_single(h5_path, event_name, zarr_path, mode)


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
