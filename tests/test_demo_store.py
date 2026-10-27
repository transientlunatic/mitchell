"""scripts/build_demo_store.py: trim a metafile into a small demo store."""

import importlib.util
from pathlib import Path

import numpy as np
import pytest
from pesummary_h5 import make_pesummary_h5

from mitchell import MitchellStore

SCRIPT = Path(__file__).parent.parent / "scripts" / "build_demo_store.py"
spec = importlib.util.spec_from_file_location("build_demo_store", SCRIPT)
demo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


def test_thin_indices_spans_the_samples() -> None:
    rows = demo.thin_indices(1000, 10)
    assert len(rows) == 10
    assert rows[0] == 0
    assert rows[-1] == 999
    assert np.all(np.diff(rows) > 0)


def test_thin_indices_keeps_everything_when_short() -> None:
    assert list(demo.thin_indices(5, 10)) == [0, 1, 2, 3, 4]


def test_downgrade_nested_sums_blocks_and_preserves_probability() -> None:
    nside_in, nside_out = 8, 2
    prob = np.random.default_rng(0).random(12 * nside_in**2)
    prob /= prob.sum()
    out = demo.downgrade_nested(prob, nside_out)
    assert out.shape == (12 * nside_out**2,)
    assert out.sum() == pytest.approx(1.0)
    # In NESTED ordering a coarse pixel owns one contiguous block of children.
    assert out[0] == pytest.approx(prob[:16].sum())
    assert out[-1] == pytest.approx(prob[-16:].sum())


def test_downgrade_rejects_upsampling_and_bad_sizes() -> None:
    with pytest.raises(ValueError, match="upsample"):
        demo.downgrade_nested(np.ones(48), 4)
    with pytest.raises(ValueError, match="valid HEALPix"):
        demo.nside_of(50)


def test_build_demo_store(tmp_path) -> None:
    h5_path = tmp_path / "meta.h5"
    make_pesummary_h5(h5_path, n_samples=200, nside=8)
    out = tmp_path / "demo.zarr"

    demo.build_demo_store(h5_path, "GW000001_000000", out, n_samples=50, nside=2)

    store = MitchellStore.open(out, mode="r")
    assert [e.name for e in store] == ["GW000001_000000"]
    event = store["GW000001_000000"]
    assert [a.name for a in event] == ["C01:IMRPhenomXPHM", "C01:SEOBNRv4PHM"]

    a = event["C01:IMRPhenomXPHM"]
    assert a.posterior["mass_1"].shape == (50,)
    assert a.priors["samples"]["mass_1"].shape == (50,)
    assert a.psds["H1"].shape == (16, 2)  # not thinned
    assert a.calibration_envelope["H1"].shape == (300, 7)
    assert a.skymap["data"].shape == (48,)
    assert a.skymap["data"][:].sum() == pytest.approx(1.0)
    assert a.skymap.attrs["nside"] == 2
    assert a.config == {"sampler": "dynesty"}
    assert dict(a.attrs)["trimmed_from"] == {
        "posterior_samples": [200, 50],
        "skymap_nside": [8, 2],
    }

    entry = store._index()["events"]["GW000001_000000"]["C01:IMRPhenomXPHM"]
    assert entry["n_samples"] == 50
    assert entry["skymap"]["shape"] == [48]


def test_build_demo_store_rejects_ring_skymaps(tmp_path) -> None:
    import h5py

    h5_path = tmp_path / "meta.h5"
    make_pesummary_h5(h5_path, nside=8)
    with h5py.File(h5_path, "r+") as f:
        for name in ("C01:IMRPhenomXPHM", "C01:SEOBNRv4PHM"):
            del f[name]["skymap/meta_data/nest"]
            f[name]["skymap/meta_data/nest"] = np.array([b"False"])
    with pytest.raises(ValueError, match="NESTED"):
        demo.build_demo_store(h5_path, "GW000001_000000", tmp_path / "o.zarr")


def test_build_demo_store_tolerates_empty_prior_samples(tmp_path) -> None:
    """Some real analyses have a ``priors/samples`` group with no arrays."""
    import h5py

    h5_path = tmp_path / "meta.h5"
    make_pesummary_h5(h5_path, nside=2)
    with h5py.File(h5_path, "r+") as f:
        for name in ("C01:IMRPhenomXPHM", "C01:SEOBNRv4PHM"):
            del f[name]["priors/samples"]
            f[name].create_group("priors/samples")
    out = tmp_path / "demo.zarr"
    demo.build_demo_store(h5_path, "GW000001_000000", out, n_samples=10, nside=2)
    a = MitchellStore.open(out, mode="r")["GW000001_000000"]["C01:IMRPhenomXPHM"]
    assert a.posterior["mass_1"].shape == (10,)
    assert dict(a.priors["analytic"].attrs) == {"mass_1": "Uniform(5, 100)"}
