"""Mitchell command-line interface."""

import click

from mitchell.store import MitchellStore


@click.group()
@click.version_option(package_name="mitchell")
def cli() -> None:
    """Mitchell — gravitational-wave analysis data tools."""


@cli.command("from-pesummary")
@click.argument("h5_path", type=click.Path(exists=True, dir_okay=False))
@click.argument("event_name")
@click.argument("zarr_path", type=click.Path())
def from_pesummary_h5(h5_path: str, event_name: str, zarr_path: str) -> None:
    """Translate a GWTC pesummary HDF5 file into a Mitchell zarr store.

    \b
    H5_PATH     Path to the source .h5 file.
    EVENT_NAME  Event identifier, e.g. GW150914_095045.
    ZARR_PATH   Destination directory for the zarr store.
    """
    click.echo(f"Translating {h5_path} → {zarr_path} (event: {event_name})")
    MitchellStore.from_pesummary_h5(h5_path, event_name, zarr_path)
    click.echo("Done.")
