"""Populate a MitchellStore from the gwresults GWTC registry.

Requires the optional ``gwresults`` package (not on PyPI — see the ``gwtc``
extra in ``pyproject.toml``). Imported lazily so the rest of mitchell has no
hard dependency on it.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

from mitchell.store import MitchellStore


class ConversionResult(NamedTuple):
    """Outcome of processing a single event in a `from-gwtc` run."""

    event_name: str
    status: str  # "converted" | "skipped" | "failed"
    detail: str = ""


def iter_gwtc_events(catalogues: list[str] | None = None) -> list[str]:
    """List event names from the gwresults registry.

    Parameters
    ----------
    catalogues:
        If given, restrict to these catalogues (e.g. ``["GWTC-2.1"]``).
        Defaults to every catalogue in the registry.
    """
    from gwresults import registry

    if not catalogues:
        return list(registry.list_events())
    names: set[str] = set()
    for catalogue in catalogues:
        names.update(registry.list_events(catalogue=catalogue))
    return sorted(names)


def build_from_gwtc(
    zarr_path: str | os.PathLike[str],
    catalogues: list[str] | None = None,
    events: list[str] | None = None,
    limit: int | None = None,
    keep_cache: bool = False,
) -> Iterator[ConversionResult]:
    """Fetch and convert GWTC events into *zarr_path*, one at a time.

    Each event is downloaded via ``gwresults`` (cached, hash-verified),
    converted into the store, and then its cached HDF5 file is deleted
    (unless *keep_cache*) — so peak local disk use stays to roughly one
    file's worth regardless of how many events are processed. Events
    already present in the store are skipped, so an interrupted run can
    simply be re-invoked.

    Parameters
    ----------
    zarr_path:
        Destination zarr store (created if absent, appended to otherwise).
    catalogues:
        Restrict to these catalogues. Defaults to every catalogue in the
        gwresults registry.
    events:
        Restrict to these specific event names. Overrides *catalogues*.
    limit:
        Process at most this many events.
    keep_cache:
        Keep each downloaded HDF5 in the gwresults cache instead of
        deleting it after conversion.

    Yields
    ------
    ConversionResult
        One per event, in processing order.
    """
    from gwresults import cache as gw_cache

    store = MitchellStore.open(zarr_path, mode="a")
    names = list(events) if events else iter_gwtc_events(catalogues)
    if limit is not None:
        names = names[:limit]

    for name in names:
        if name in store:
            yield ConversionResult(name, "skipped", "already present")
            continue

        try:
            h5_path = gw_cache.fetch(name)
        except Exception as exc:  # registry lookup / network / hash errors
            yield ConversionResult(name, "failed", f"fetch error: {exc}")
            continue

        try:
            MitchellStore.from_pesummary_h5(h5_path, name, zarr_path, mode="a")
        except Exception as exc:  # unexpected HDF5 layout, etc.
            # A failure partway through can leave a partially-written group;
            # remove it so the event is retried (not silently skipped) next run.
            if name in store:
                del store[name]
            yield ConversionResult(name, "failed", f"convert error: {exc}")
            continue
        finally:
            if not keep_cache:
                Path(h5_path).unlink(missing_ok=True)

        yield ConversionResult(name, "converted")
