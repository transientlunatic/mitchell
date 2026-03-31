"""MitchellStore, Event, and Analysis — core public API."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Iterator

import numpy as np
import zarr

if TYPE_CHECKING:
    import arviz as az

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_META_ATTRS = [
    "approximant", "cosmology", "delta_f", "distance_marginalization",
    "duration", "f_final", "f_low", "f_ref", "phase_marginalization",
    "reference_frame", "sampling_frequency", "start_time",
    "time_marginalization", "time_reference",
]


def _decode(val: object) -> object:
    """Unwrap length-1 arrays and decode byte strings for zarr attributes."""
    if isinstance(val, np.ndarray) and val.ndim == 1 and len(val) == 1:
        val = val[0]
    if isinstance(val, (bytes, np.bytes_)):
        val = val.decode()
    return val


def _columnar_to_dict(group: zarr.Group) -> dict[str, np.ndarray]:
    """Return {param: array} for every array dataset in *group*."""
    return {k: group[k][:] for k in group.array_keys()}


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
    def attrs(self) -> zarr.attrs.Attributes:
        return self._group.attrs

    # -- data product properties --------------------------------------------

    @property
    def posterior(self) -> zarr.Group | None:
        """Zarr group of columnar posterior sample arrays, or None."""
        if "posterior" in self._group and "samples" in self._group["posterior"]:
            return self._group["posterior"]["samples"]
        return None

    @property
    def priors(self) -> zarr.Group | None:
        """Zarr group containing ``samples`` and/or ``analytic`` sub-groups."""
        if "priors" in self._group:
            return self._group["priors"]
        return None

    @property
    def psds(self) -> zarr.Group | None:
        """Zarr group of PSD arrays keyed by detector name."""
        if "psds" in self._group:
            return self._group["psds"]
        return None

    @property
    def calibration_envelope(self) -> zarr.Group | None:
        """Zarr group of calibration envelope arrays keyed by detector."""
        if "calibration_envelope" in self._group:
            return self._group["calibration_envelope"]
        return None

    @property
    def skymap(self) -> zarr.Group | None:
        """Zarr group containing the HEALPix skymap ``data`` array."""
        if "skymap" in self._group:
            return self._group["skymap"]
        return None

    @property
    def config(self) -> dict[str, object]:
        """Config file key-value pairs as a plain dict."""
        if "config_file" in self._group:
            return dict(self._group["config_file"].attrs)
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
        import arviz as az

        data: dict[str, dict[str, np.ndarray]] = {}

        if self.posterior is not None:
            post = _columnar_to_dict(self.posterior)
            # ArviZ expects (chain, draw, ...) — reshape flat draws to (1, N)
            data["posterior"] = {k: v[np.newaxis, :] for k, v in post.items()}

        if self.priors is not None and "samples" in self.priors:
            prior = _columnar_to_dict(self.priors["samples"])
            data["prior"] = {k: v[np.newaxis, :] for k, v in prior.items()}

        if self.psds is not None:
            psd_data = {det: self.psds[det][:] for det in self.psds.array_keys()}
            data["observed_data"] = psd_data

        return az.from_dict(data)

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
    """

    def __init__(self, group: zarr.Group) -> None:
        self._group = group

    @property
    def name(self) -> str:
        return self._group.name.split("/")[-1]

    def __getitem__(self, analysis_name: str) -> Analysis:
        return Analysis(self._group[analysis_name])

    def __iter__(self) -> Iterator[Analysis]:
        for key in self._group.group_keys():
            yield Analysis(self._group[key])

    def __len__(self) -> int:
        return sum(1 for _ in self._group.group_keys())

    def __repr__(self) -> str:
        names = [a.name for a in self]
        return f"Event({self.name!r}, analyses={names})"


# ---------------------------------------------------------------------------
# MitchellStore
# ---------------------------------------------------------------------------

class MitchellStore:
    """A zarr-backed store of gravitational-wave analysis data products.

    Open an existing store or create a new one with
    :meth:`MitchellStore.open`.  To import from a GWTC-style bilby HDF5
    file use :meth:`MitchellStore.from_bilby_h5`.

    Parameters
    ----------
    store:
        Any zarr v3 :class:`zarr.storage.StoreLike`.
    mode:
        Passed to :func:`zarr.open_group`.  Use ``"r"`` for read-only,
        ``"a"`` to open existing or create, ``"w"`` to overwrite.
    """

    SCHEMA_VERSION = "0.1.0"

    def __init__(
        self,
        store: zarr.storage.StoreLike,
        mode: str = "a",
    ) -> None:
        self._store = store
        self._root = zarr.open_group(store=store, mode=mode)
        if mode != "r" and "mitchell_schema_version" not in self._root.attrs:
            self._root.attrs["mitchell_schema_version"] = self.SCHEMA_VERSION

    # -- constructors -------------------------------------------------------

    @classmethod
    def open(
        cls,
        path: str | os.PathLike,
        mode: str = "a",
    ) -> MitchellStore:
        """Open (or create) a store at *path* on the local filesystem."""
        store = zarr.storage.LocalStore(Path(path))
        return cls(store, mode=mode)

    @classmethod
    def from_bilby_h5(
        cls,
        h5_path: str | os.PathLike,
        event_name: str,
        zarr_path: str | os.PathLike,
    ) -> MitchellStore:
        """Translate a GWTC bilby HDF5 file into a new Mitchell zarr store.

        Parameters
        ----------
        h5_path:
            Path to the source ``*.h5`` file.
        event_name:
            Human-readable event identifier, e.g. ``"GW150914_095045"``.
        zarr_path:
            Destination directory for the new zarr store.

        Returns
        -------
        MitchellStore
            The newly created store, opened in append mode.
        """
        import h5py as h5

        instance = cls.open(zarr_path, mode="w")
        root = instance._root
        event = root.require_group(f"events/{event_name}")

        with h5.File(h5_path, "r") as f:
            for analysis_name, h5_group in f.items():
                analysis = event.require_group(analysis_name)

                # -- meta_data attributes --
                if (
                    "meta_data" in h5_group
                    and "meta_data" in h5_group["meta_data"]
                ):
                    md = h5_group["meta_data"]["meta_data"]
                    analysis.attrs.update(
                        {k: _decode(md[k][()]) for k in _META_ATTRS if k in md}
                    )

                if "version" in h5_group:
                    analysis.attrs["version"] = _decode(h5_group["version"][()])
                if "description" in h5_group:
                    analysis.attrs["description"] = _decode(
                        h5_group["description"][()]
                    )

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
                    for detector, dataset in h5_group[
                        "calibration_envelope"
                    ].items():
                        cal_group[detector] = dataset[()]

                # -- config file --
                if (
                    "config_file" in h5_group
                    and "config" in h5_group["config_file"]
                ):
                    config_group = analysis.require_group("config_file")
                    config_group.attrs.update(
                        {
                            k: _decode(v[()])
                            for k, v in h5_group["config_file"][
                                "config"
                            ].items()
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

        zarr.consolidate_metadata(instance._store)
        return instance

    # -- event access -------------------------------------------------------

    def __getitem__(self, event_name: str) -> Event:
        return Event(self._root["events"][event_name])

    def __iter__(self) -> Iterator[Event]:
        if "events" not in self._root:
            return
        for key in self._root["events"].group_keys():
            yield Event(self._root["events"][key])

    def __len__(self) -> int:
        if "events" not in self._root:
            return 0
        return sum(1 for _ in self._root["events"].group_keys())

    def __repr__(self) -> str:
        n = len(self)
        return f"MitchellStore({n} event{'s' if n != 1 else ''})"
