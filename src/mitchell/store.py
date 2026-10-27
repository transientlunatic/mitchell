"""MitchellStore, Event, and Analysis — core public API."""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import numpy as np
import zarr

if TYPE_CHECKING:
    import arviz as az

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

Mode = Literal["r", "r+", "a", "w", "w-"]
OnConflict = Literal["skip", "replace", "error"]

_META_ATTRS = [
    "approximant",
    "cosmology",
    "delta_f",
    "distance_marginalization",
    "duration",
    "f_final",
    "f_low",
    "f_ref",
    "phase_marginalization",
    "reference_frame",
    "sampling_frequency",
    "start_time",
    "time_marginalization",
    "time_reference",
]


def _decode(val: Any) -> Any:
    """Unwrap length-1 arrays and decode byte strings for zarr attributes."""
    if isinstance(val, np.ndarray) and val.ndim == 1 and len(val) == 1:
        val = val[0]
    if isinstance(val, np.generic):
        # e.g. np.int64 isn't JSON-serializable (unlike np.float64, which
        # subclasses the builtin float); .item() gives the native Python type.
        val = val.item()
    if isinstance(val, (bytes, np.bytes_)):
        val = val.decode()
    return val


def _as_group(node: object, path: str) -> zarr.Group:
    """Narrow a zarr node to a group (zarr's ``__getitem__`` returns a union)."""
    if not isinstance(node, zarr.Group):
        raise TypeError(f"{path!r} is not a zarr group")
    return node


def analysis_groups(h5_file: Any) -> dict[str, Any]:
    """The analysis groups of an open PESummary metafile, by label.

    A metafile holds one group per analysis (each with ``posterior_samples``)
    next to file-level groups such as ``history`` and ``version``, which
    describe the file itself and are not analyses.
    """
    return {
        label: group
        for label, group in h5_file.items()
        if hasattr(group, "keys") and "posterior_samples" in group
    }


def _subgroup(group: zarr.Group, key: str) -> zarr.Group | None:
    """Return ``group[key]`` if it exists (and is a group), else None."""
    return _as_group(group[key], key) if key in group else None


def _array_shapes(group: zarr.Group | None) -> dict[str, list[int]]:
    """``{name: shape}`` for every array directly inside *group*."""
    if group is None:
        return {}
    return {k: list(group[k].shape) for k in sorted(group.array_keys())}  # type: ignore[union-attr]


def _analysis_index_entry(group: zarr.Group) -> dict[str, Any]:
    """Summarise one analysis group for the root ``mitchell_index``.

    Holds everything needed to *list* what a store contains without further
    requests: names and shapes of the data products plus the small attribute
    blocks.  Bulk arrays and the (larger) config file are not copied.
    """
    entry: dict[str, Any] = {"attrs": dict(group.attrs)}

    posterior = _subgroup(group, "posterior")
    samples = _subgroup(posterior, "samples") if posterior is not None else None
    shapes = _array_shapes(samples)
    entry["posterior"] = sorted(shapes)
    if shapes:
        entry["n_samples"] = next(iter(shapes.values()))[0]

    priors = _subgroup(group, "priors")
    if priors is not None:
        prior_samples = _subgroup(priors, "samples")
        analytic = _subgroup(priors, "analytic")
        entry["priors"] = {
            "samples": sorted(_array_shapes(prior_samples)),
            "analytic": dict(analytic.attrs) if analytic is not None else {},
        }

    entry["psds"] = _array_shapes(_subgroup(group, "psds"))
    entry["calibration_envelope"] = _array_shapes(
        _subgroup(group, "calibration_envelope")
    )

    skymap = _subgroup(group, "skymap")
    if skymap is not None and "data" in skymap:
        entry["skymap"] = {
            "attrs": dict(skymap.attrs),
            "shape": list(skymap["data"].shape),  # type: ignore[union-attr]
        }

    if "config_file" in group:
        entry["config_file"] = True
    return entry


def _event_index_entry(group: zarr.Group) -> dict[str, Any]:
    return {
        key: _analysis_index_entry(_as_group(group[key], key))
        for key in sorted(group.group_keys())
    }


def _columnar_to_dict(group: zarr.Group) -> dict[str, np.ndarray]:
    """Return {param: array} for every array dataset in *group*."""
    return {k: np.asarray(group[k][:]) for k in group.array_keys()}  # type: ignore[index]


@dataclass
class MergeResult:
    """What :meth:`MitchellStore.merge` did, by event name."""

    added: list[str] = field(default_factory=list)
    replaced: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


class Analysis:
    """A single PE analysis (waveform approximant run) within an event.

    Parameters
    ----------
    group:
        The zarr group at ``events/{event_name}/{analysis_name}``.
    """

    def __init__(self, group: zarr.Group) -> None:
        self._group = group

    @property
    def name(self) -> str:
        return self._group.name.split("/")[-1]

    @property
    def attrs(self) -> Mapping[str, Any]:
        return self._group.attrs

    # -- data product properties --------------------------------------------

    @property
    def posterior(self) -> zarr.Group | None:
        """Zarr group of columnar posterior sample arrays, or None."""
        if "posterior" in self._group:
            posterior = _as_group(self._group["posterior"], "posterior")
            if "samples" in posterior:
                return _as_group(posterior["samples"], "posterior/samples")
        return None

    @property
    def priors(self) -> zarr.Group | None:
        """Zarr group containing ``samples`` and/or ``analytic`` sub-groups."""
        if "priors" in self._group:
            return _as_group(self._group["priors"], "priors")
        return None

    @property
    def psds(self) -> zarr.Group | None:
        """Zarr group of PSD arrays keyed by detector name."""
        if "psds" in self._group:
            return _as_group(self._group["psds"], "psds")
        return None

    @property
    def calibration_envelope(self) -> zarr.Group | None:
        """Zarr group of calibration envelope arrays keyed by detector."""
        if "calibration_envelope" in self._group:
            return _as_group(
                self._group["calibration_envelope"], "calibration_envelope"
            )
        return None

    @property
    def skymap(self) -> zarr.Group | None:
        """Zarr group containing the HEALPix skymap ``data`` array."""
        if "skymap" in self._group:
            return _as_group(self._group["skymap"], "skymap")
        return None

    @property
    def config(self) -> dict[str, object]:
        """Config file key-value pairs as a plain dict."""
        if "config_file" in self._group:
            return dict(_as_group(self._group["config_file"], "config_file").attrs)
        return {}

    # -- ArviZ conversion ---------------------------------------------------

    def to_arviz(self) -> az.InferenceData:
        """Convert to an :class:`arviz.InferenceData` object.

        Posterior and prior samples are each loaded into memory and placed
        into the corresponding ArviZ groups.  All other data products
        (PSDs, calibration, skymap) are attached as
        ``constant_data`` / ``observed_data`` where appropriate.

        Returns
        -------
        arviz.InferenceData
        """
        try:
            import arviz as az
        except ImportError as exc:
            raise ImportError(
                "to_arviz() requires arviz: pip install 'mitchell[arviz]'"
            ) from exc

        data: dict[str, dict[str, np.ndarray]] = {}

        if self.posterior is not None:
            post = _columnar_to_dict(self.posterior)
            # ArviZ expects (chain, draw, ...) — reshape flat draws to (1, N)
            data["posterior"] = {k: v[np.newaxis, :] for k, v in post.items()}

        if self.priors is not None and "samples" in self.priors:
            prior = _columnar_to_dict(
                _as_group(self.priors["samples"], "priors/samples")
            )
            data["prior"] = {k: v[np.newaxis, :] for k, v in prior.items()}

        if self.psds is not None:
            psd_data = _columnar_to_dict(self.psds)
            data["observed_data"] = psd_data

        # ArviZ 1.x takes a dict of groups; 0.x takes one keyword per group.
        if int(az.__version__.split(".")[0]) >= 1:
            return az.from_dict(data)
        return az.from_dict(**data)

    def __repr__(self) -> str:
        return f"Analysis({self.name!r})"


# ---------------------------------------------------------------------------
# Event
# ---------------------------------------------------------------------------


class Event:
    """A gravitational-wave event containing one or more analyses.

    Parameters
    ----------
    group:
        The zarr group at ``events/{event_name}``.
    analysis_names:
        Analysis names already known from the store index.  When omitted
        they are discovered by listing the group, which not every store
        backend (e.g. plain HTTP) supports.
    """

    def __init__(
        self, group: zarr.Group, analysis_names: list[str] | None = None
    ) -> None:
        self._group = group
        self._names = analysis_names

    def _analysis_names(self) -> list[str]:
        if self._names is not None:
            return list(self._names)
        return sorted(self._group.group_keys())

    @property
    def name(self) -> str:
        return self._group.name.split("/")[-1]

    def __getitem__(self, analysis_name: str) -> Analysis:
        return Analysis(_as_group(self._group[analysis_name], analysis_name))

    def __iter__(self) -> Iterator[Analysis]:
        for key in self._analysis_names():
            yield Analysis(_as_group(self._group[key], key))

    def __len__(self) -> int:
        return len(self._analysis_names())

    def __repr__(self) -> str:
        names = [a.name for a in self]
        return f"Event({self.name!r}, analyses={names})"


# ---------------------------------------------------------------------------
# MitchellStore
# ---------------------------------------------------------------------------


class MitchellStore:
    """A zarr-backed store of gravitational-wave analysis data products.

    Open an existing store or create a new one with
    :meth:`MitchellStore.open`.  To import from a GWTC-style PEsummary HDF5
    file use :meth:`MitchellStore.from_pesummary_h5`.

    Parameters
    ----------
    store:
        Any zarr v3 :class:`zarr.storage.StoreLike`.
    mode:
        Passed to :func:`zarr.open_group`.  Use ``"r"`` for read-only,
        ``"a"`` to open existing or create, ``"w"`` to overwrite.
    """

    SCHEMA_VERSION = "0.2.0"
    INDEX_ATTR = "mitchell_index"

    def __init__(
        self,
        store: zarr.storage.StoreLike,
        mode: Mode = "a",
    ) -> None:
        self._store = store
        # Consolidated metadata (written by schema 0.1.0) is not part of the
        # zarr v3 spec and goes stale as soon as the store is appended to, so
        # never trust it; the root ``mitchell_index`` replaces it.
        self._root = zarr.open_group(store=store, mode=mode, use_consolidated=False)
        if mode != "r" and "mitchell_schema_version" not in self._root.attrs:
            self._root.attrs.update(
                {
                    "mitchell_schema_version": self.SCHEMA_VERSION,
                    self.INDEX_ATTR: {"events": {}},
                }
            )

    # -- schema version and index -------------------------------------------

    @property
    def schema_version(self) -> str | None:
        """The ``mitchell_schema_version`` recorded in the store root."""
        version = self._root.attrs.get("mitchell_schema_version")
        return str(version) if version is not None else None

    def _index(self) -> dict[str, Any] | None:
        """The root event index, or None for a store written before 0.2.0."""
        index = self._root.attrs.get(self.INDEX_ATTR)
        return index if isinstance(index, dict) else None

    def rebuild_index(self) -> None:
        """(Re)build the root ``mitchell_index`` by scanning every event.

        Also upgrades a schema 0.1.0 store in place: the stale consolidated
        metadata is dropped and the schema version is bumped.  Needs a store
        that can list its groups, so run it on local storage.
        """
        events: dict[str, Any] = {}
        if "events" in self._root:
            for name in sorted(self._events.group_keys()):
                events[name] = _event_index_entry(_as_group(self._events[name], name))
        self._root.attrs.update(
            {
                "mitchell_schema_version": self.SCHEMA_VERSION,
                self.INDEX_ATTR: {"events": events},
            }
        )

    def _update_index(self, event_name: str) -> None:
        """Refresh the index entry for *event_name* (drop it if the event is gone)."""
        index = self._index()
        if index is None:
            self.rebuild_index()
            return
        events = dict(index.get("events", {}))
        if event_name in self:
            events[event_name] = _event_index_entry(
                _as_group(self._events[event_name], event_name)
            )
        else:
            events.pop(event_name, None)
        self._root.attrs[self.INDEX_ATTR] = {"events": dict(sorted(events.items()))}

    def merge(
        self,
        parts: Iterable[str | os.PathLike[str]],
        on_conflict: OnConflict = "skip",
        move: bool = False,
    ) -> MergeResult:
        """Merge the events of other Mitchell stores into this one.

        This is how a catalogue is assembled from stores built independently
        (one per event, say, by parallel jobs): an event is a directory tree, so
        merging moves or copies it into place and writes this store's index
        once, from the parts' own indexes, instead of re-scanning anything.

        Parameters
        ----------
        parts:
            Paths of local Mitchell stores.
        on_conflict:
            What to do when an event is already in this store: ``"skip"`` it
            (the default, so a merge can be re-run), ``"replace"`` it, or
            ``"error"`` out before changing anything.
        move:
            Move event directories out of the parts instead of copying them
            (a rename on the same filesystem, so no second copy of the data).
            A part left with no events is removed.

        Both this store and the parts must be on the local filesystem.
        """
        if not isinstance(self._store, zarr.storage.LocalStore):
            raise TypeError("merge() needs a store on the local filesystem")
        target_events = Path(self._store.root) / "events"

        part_stores: list[tuple[Path, MitchellStore]] = []
        for part in parts:
            try:
                opened = MitchellStore.open(part, mode="r")
            except Exception as exc:
                raise ValueError(f"{part} is not a Mitchell store: {exc}") from exc
            if opened.schema_version is None:
                raise ValueError(f"{part} is not a Mitchell store (no schema version)")
            part_stores.append((Path(part), opened))

        if on_conflict == "error":
            clashes = [
                name
                for _, opened in part_stores
                for name in opened._event_names()
                if name in self
            ]
            if clashes:
                raise ValueError(
                    f"{len(clashes)} event(s) already in the store: "
                    + ", ".join(sorted(set(clashes))[:5])
                )

        result = MergeResult()
        entries: dict[str, Any] = {}
        self._root.require_group("events")
        for path, opened in part_stores:
            index = opened._index()
            fully_merged = True
            for name in opened._event_names():
                destination = target_events / name
                if name in self:
                    if on_conflict == "skip":
                        result.skipped.append(name)
                        fully_merged = False
                        continue
                    shutil.rmtree(destination)
                    result.replaced.append(name)
                else:
                    result.added.append(name)
                source = path / "events" / name
                if move:
                    shutil.move(source, destination)
                else:
                    shutil.copytree(source, destination)
                if index is not None and name in index.get("events", {}):
                    entries[name] = index["events"][name]
                else:
                    entries[name] = _event_index_entry(
                        _as_group(self._events[name], name)
                    )
            if move and fully_merged:
                shutil.rmtree(path)

        if self._index() is None:
            self.rebuild_index()  # a legacy store: index everything, once
        elif entries:
            events = {**self._index().get("events", {}), **entries}  # type: ignore[union-attr]
            self._root.attrs[self.INDEX_ATTR] = {"events": dict(sorted(events.items()))}
        return result

    def _event_names(self) -> list[str]:
        index = self._index()
        if index is not None:
            return sorted(index.get("events", {}))
        if "events" not in self._root:
            return []
        return sorted(self._events.group_keys())

    # -- constructors -------------------------------------------------------

    @classmethod
    def open(
        cls,
        path: str | os.PathLike[str],
        mode: Mode = "a",
    ) -> MitchellStore:
        """Open (or create) a store at *path* on the local filesystem."""
        store = zarr.storage.LocalStore(Path(path))
        return cls(store, mode=mode)

    @classmethod
    def from_pesummary_h5(
        cls,
        h5_path: str | os.PathLike[str],
        event_name: str,
        zarr_path: str | os.PathLike[str],
        mode: Mode = "a",
    ) -> MitchellStore:
        """Translate a GWTC pesummary HDF5 file into a Mitchell zarr store.

        Parameters
        ----------
        h5_path:
            Path to the source ``*.h5`` file.
        event_name:
            Human-readable event identifier, e.g. ``"GW150914_095045"``.
        zarr_path:
            Destination directory for the zarr store.
        mode:
            Zarr open mode.  Use ``"a"`` (default) to append an event to an
            existing store, or ``"w"`` to overwrite the store from scratch.

        Returns
        -------
        MitchellStore
            The store, opened in the requested mode.
        """
        import h5py as h5

        instance = cls.open(zarr_path, mode=mode)
        root = instance._root
        event = root.require_group(f"events/{event_name}")

        with h5.File(h5_path, "r") as f:
            for analysis_name, h5_group in analysis_groups(f).items():
                analysis = event.require_group(analysis_name)

                # -- meta_data attributes --
                if "meta_data" in h5_group and "meta_data" in h5_group["meta_data"]:
                    md = h5_group["meta_data"]["meta_data"]
                    analysis.attrs.update(
                        {k: _decode(md[k][()]) for k in _META_ATTRS if k in md}
                    )

                if "version" in h5_group:
                    analysis.attrs["version"] = _decode(h5_group["version"][()])
                if "description" in h5_group:
                    analysis.attrs["description"] = _decode(h5_group["description"][()])

                # -- posterior samples --
                if "posterior_samples" in h5_group:
                    samples = h5_group["posterior_samples"][()]
                    post_group = analysis.require_group("posterior/samples")
                    for param in samples.dtype.names:
                        post_group[param] = samples[param]

                # -- prior samples + analytic priors --
                if "priors" in h5_group:
                    priors = h5_group["priors"]
                    if "samples" in priors:
                        prior_samples = analysis.require_group("priors/samples")
                        for param, dataset in priors["samples"].items():
                            prior_samples[param] = dataset[()]
                    if "analytic" in priors and len(priors["analytic"]) > 0:
                        analytic_group = analysis.require_group("priors/analytic")
                        analytic_group.attrs.update(
                            {
                                k: _decode(v[()])
                                for k, v in priors["analytic"].items()
                                if isinstance(v, h5.Dataset)
                            }
                        )

                # -- PSDs --
                if "psds" in h5_group:
                    psds_group = analysis.require_group("psds")
                    for detector, dataset in h5_group["psds"].items():
                        psds_group[detector] = dataset[()]

                # -- calibration envelope --
                if "calibration_envelope" in h5_group:
                    cal_group = analysis.require_group("calibration_envelope")
                    for detector, dataset in h5_group["calibration_envelope"].items():
                        cal_group[detector] = dataset[()]

                # -- config file --
                if "config_file" in h5_group and "config" in h5_group["config_file"]:
                    config_group = analysis.require_group("config_file")
                    config_group.attrs.update(
                        {
                            k: _decode(v[()])
                            for k, v in h5_group["config_file"]["config"].items()
                            if isinstance(v, h5.Dataset)
                        }
                    )

                # -- skymap --
                if "skymap" in h5_group:
                    skymap_group = analysis.require_group("skymap")
                    skymap_h5 = h5_group["skymap"]
                    if "data" in skymap_h5:
                        skymap_group["data"] = skymap_h5["data"][()]
                    if "meta_data" in skymap_h5:
                        skymap_group.attrs.update(
                            {
                                k: _decode(v[()])
                                for k, v in skymap_h5["meta_data"].items()
                                if isinstance(v, h5.Dataset)
                            }
                        )

        instance._update_index(event_name)
        return instance

    # -- event access -------------------------------------------------------

    @property
    def _events(self) -> zarr.Group:
        return _as_group(self._root["events"], "events")

    def _event(self, event_name: str) -> Event:
        index = self._index()
        names = None
        if index is not None and event_name in index.get("events", {}):
            names = sorted(index["events"][event_name])
        return Event(_as_group(self._events[event_name], event_name), names)

    def __getitem__(self, event_name: str) -> Event:
        return self._event(event_name)

    def __contains__(self, event_name: str) -> bool:
        # Checks the group itself, not the index, so a half-written event
        # (written but not yet indexed) is still found and can be cleaned up.
        return "events" in self._root and event_name in self._events

    def __delitem__(self, event_name: str) -> None:
        del self._events[event_name]
        self._update_index(event_name)

    def __iter__(self) -> Iterator[Event]:
        for name in self._event_names():
            yield self._event(name)

    def __len__(self) -> int:
        return len(self._event_names())

    def __repr__(self) -> str:
        n = len(self)
        return f"MitchellStore({n} event{'s' if n != 1 else ''})"
