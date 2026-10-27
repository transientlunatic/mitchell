"""Build a small demo store from one PESummary metafile.

The full GWTC-2.1 file for GW150914 is 134 MB, too heavy to commit and serve
from a static site.  This keeps every analysis but thins the posterior and
prior samples and downsamples the skymap, so the result is a few MB and still
exercises everything the viewer shows::

    python scripts/build_demo_store.py \\
        IGWN-GWTC2p1-v2-GW150914_095045_PEDataRelease_mixed_cosmo.h5 \\
        GW150914_095045 out/events.zarr

Each analysis records what was trimmed in a ``trimmed_from`` attribute so a
reader of the demo is not misled about its resolution.
"""

from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path
from typing import Any

import numpy as np
import zarr

from mitchell import MitchellStore

DEFAULT_SAMPLES = 5000
DEFAULT_NSIDE = 128


def thin_indices(n: int, keep: int) -> np.ndarray:
    """*keep* evenly spaced indices into *n* samples (all of them if n <= keep)."""
    if n <= keep:
        return np.arange(n)
    return np.unique(np.linspace(0, n - 1, keep).round().astype(int))


def nside_of(npix: int) -> int:
    nside = int(round((npix / 12) ** 0.5))
    if 12 * nside * nside != npix:
        raise ValueError(f"{npix} is not a valid HEALPix pixel count")
    return nside


def downgrade_nested(prob: np.ndarray, nside: int) -> np.ndarray:
    """Downsample a NESTED per-pixel probability map to *nside*.

    In NESTED ordering the children of a pixel are consecutive, so a coarser
    pixel's probability is the sum of a contiguous block.
    """
    nside_in = nside_of(len(prob))
    if nside > nside_in:
        raise ValueError(f"cannot upsample nside {nside_in} to {nside}")
    ratio = (nside_in // nside) ** 2
    return prob.reshape(12 * nside * nside, ratio).sum(axis=1)


def _length(group: zarr.Group) -> int | None:
    """Length of the arrays in *group* (they share one), or None if it has none."""
    for name in group.array_keys():
        return int(group[name].shape[0])  # type: ignore[union-attr]
    return None


def _copy_attrs(src: zarr.Group, dst: zarr.Group) -> None:
    dst.attrs.update(dict(src.attrs))


def _copy_arrays(src: zarr.Group, dst: zarr.Group, rows: np.ndarray | None) -> None:
    for name in src.array_keys():
        data = np.asarray(src[name][:])  # type: ignore[index]
        dst[name] = data if rows is None else data[rows]


def _group(parent: zarr.Group, key: str) -> zarr.Group | None:
    node = parent[key] if key in parent else None
    return node if isinstance(node, zarr.Group) else None


def _trim_analysis(
    src: zarr.Group, dst: zarr.Group, n_samples: int, nside: int
) -> None:
    _copy_attrs(src, dst)
    trimmed: dict[str, Any] = {}

    posterior = _group(_group(src, "posterior") or src, "samples")
    n = _length(posterior) if posterior is not None else None
    if posterior is not None and n is not None:
        rows = thin_indices(n, n_samples)
        _copy_arrays(posterior, dst.require_group("posterior/samples"), rows)
        trimmed["posterior_samples"] = [int(n), int(len(rows))]

    priors = _group(src, "priors")
    if priors is not None:
        out = dst.require_group("priors")
        samples = _group(priors, "samples")
        n_prior = _length(samples) if samples is not None else None
        if samples is not None and n_prior is not None:
            rows = thin_indices(n_prior, n_samples)
            _copy_arrays(samples, out.require_group("samples"), rows)
        analytic = _group(priors, "analytic")
        if analytic is not None:
            _copy_attrs(analytic, out.require_group("analytic"))

    for key in ("psds", "calibration_envelope"):
        group = _group(src, key)
        if group is not None:
            _copy_arrays(group, dst.require_group(key), None)

    config = _group(src, "config_file")
    if config is not None:
        _copy_attrs(config, dst.require_group("config_file"))

    skymap = _group(src, "skymap")
    if skymap is not None and "data" in skymap:
        attrs = dict(skymap.attrs)
        if str(attrs.get("nest")) != "True":
            raise ValueError("only NESTED skymaps can be downsampled here")
        data = np.asarray(skymap["data"][:])  # type: ignore[index]
        target = min(nside, nside_of(len(data)))
        out_sky = dst.require_group("skymap")
        out_sky["data"] = downgrade_nested(data, target)
        out_sky.attrs.update({**attrs, "nside": target})
        trimmed["skymap_nside"] = [nside_of(len(data)), target]

    dst.attrs["trimmed_from"] = trimmed


def build_demo_store(
    h5_path: Path,
    event_name: str,
    out_path: Path,
    n_samples: int = DEFAULT_SAMPLES,
    nside: int = DEFAULT_NSIDE,
) -> None:
    """Write a trimmed single-event store to *out_path* (replacing it)."""
    if out_path.exists():
        shutil.rmtree(out_path)
    with tempfile.TemporaryDirectory() as tmp:
        full_path = Path(tmp) / "full.zarr"
        full = MitchellStore.from_pesummary_h5(h5_path, event_name, full_path, mode="w")
        out = MitchellStore.open(out_path, mode="w")
        for analysis in full[event_name]:
            dst = out._root.require_group(f"events/{event_name}/{analysis.name}")
            _trim_analysis(analysis._group, dst, n_samples, nside)
        out.rebuild_index()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("h5_path", type=Path)
    parser.add_argument("event_name")
    parser.add_argument("out_path", type=Path)
    parser.add_argument("--samples", type=int, default=DEFAULT_SAMPLES)
    parser.add_argument("--nside", type=int, default=DEFAULT_NSIDE)
    args = parser.parse_args()
    build_demo_store(
        args.h5_path, args.event_name, args.out_path, args.samples, args.nside
    )
    print(f"wrote {args.out_path}")


if __name__ == "__main__":
    main()
