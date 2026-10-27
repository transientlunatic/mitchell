"""The root ``mitchell_index`` (schema 0.2.0) and migration from 0.1.0."""

import json

import numpy as np
import pytest
import zarr
from click.testing import CliRunner

from mitchell import MitchellStore
from mitchell.cli import cli

h5py = pytest.importorskip("h5py")

DETECTORS = ("H1", "L1")


def make_pesummary_h5(path, analyses=("C01:IMRPhenomXPHM", "C01:SEOBNRv4PHM")):
    """Write a small file with the layout ``from_pesummary_h5`` reads."""
    rng = np.random.default_rng(1)
    with h5py.File(path, "w") as f:
        for name in analyses:
            g = f.create_group(name)
            md = g.create_group("meta_data/meta_data")
            md["approximant"] = np.bytes_(name.split(":")[1])
            md["f_low"] = np.array([20.0])
            g["version"] = np.bytes_("1.0")
            g["description"] = np.bytes_("test run")

            dtype = [("mass_1", "f8"), ("mass_2", "f8"), ("chi_eff", "f8")]
            samples = np.zeros(40, dtype=dtype)
            for k in samples.dtype.names:
                samples[k] = rng.standard_normal(40)
            g["posterior_samples"] = samples

            g["priors/samples/mass_1"] = rng.random(40)
            g["priors/analytic/mass_1"] = np.bytes_("Uniform(5, 100)")

            for det in DETECTORS:
                g[f"psds/{det}"] = rng.random((16, 2))
                g[f"calibration_envelope/{det}"] = rng.random((300, 7))

            g["config_file/config/sampler"] = np.bytes_("dynesty")

            g["skymap/data"] = rng.random(48)
            g["skymap/meta_data/nside"] = np.array([2])


def root_json(zarr_path) -> dict:
    return json.loads((zarr_path / "zarr.json").read_text())


@pytest.fixture
def h5_file(tmp_path):
    path = tmp_path / "GW000001_000000.h5"
    make_pesummary_h5(path)
    return path


def test_new_store_has_empty_index(tmp_path):
    store = MitchellStore.open(tmp_path / "s.zarr")
    assert store.schema_version == "0.2.0"
    assert store._index() == {"events": {}}
    assert len(store) == 0


def test_conversion_populates_index(tmp_path, h5_file):
    out = tmp_path / "s.zarr"
    MitchellStore.from_pesummary_h5(h5_file, "GW000001_000000", out)

    store = MitchellStore.open(out, mode="r")
    index = store._index()
    assert list(index["events"]) == ["GW000001_000000"]

    entry = index["events"]["GW000001_000000"]["C01:IMRPhenomXPHM"]
    assert entry["attrs"]["approximant"] == "IMRPhenomXPHM"
    assert entry["posterior"] == ["chi_eff", "mass_1", "mass_2"]
    assert entry["n_samples"] == 40
    assert entry["priors"]["samples"] == ["mass_1"]
    assert entry["priors"]["analytic"] == {"mass_1": "Uniform(5, 100)"}
    assert entry["psds"] == {"H1": [16, 2], "L1": [16, 2]}
    assert entry["calibration_envelope"]["H1"] == [300, 7]
    assert entry["skymap"] == {"attrs": {"nside": 2}, "shape": [48]}
    assert entry["config_file"] is True


def test_no_consolidated_metadata_is_written(tmp_path, h5_file):
    out = tmp_path / "s.zarr"
    MitchellStore.from_pesummary_h5(h5_file, "GW000001_000000", out)
    root = root_json(out)
    assert "consolidated_metadata" not in root
    assert root["attributes"]["mitchell_schema_version"] == "0.2.0"
    assert "mitchell_index" in root["attributes"]


def test_listing_comes_from_the_index(tmp_path, h5_file):
    out = tmp_path / "s.zarr"
    MitchellStore.from_pesummary_h5(h5_file, "GW000001_000000", out)
    store = MitchellStore.open(out, mode="r")
    event = store["GW000001_000000"]
    assert event._names == ["C01:IMRPhenomXPHM", "C01:SEOBNRv4PHM"]
    assert [a.name for a in event] == event._names
    assert len(event) == 2


def test_second_event_and_delete_update_index(tmp_path, h5_file):
    out = tmp_path / "s.zarr"
    MitchellStore.from_pesummary_h5(h5_file, "GW000002_000000", out)
    MitchellStore.from_pesummary_h5(h5_file, "GW000001_000000", out)

    store = MitchellStore.open(out)
    assert [e.name for e in store] == ["GW000001_000000", "GW000002_000000"]

    del store["GW000001_000000"]
    reopened = MitchellStore.open(out, mode="r")
    assert [e.name for e in reopened] == ["GW000002_000000"]
    assert list(reopened._index()["events"]) == ["GW000002_000000"]
    assert "GW000001_000000" not in reopened


def make_legacy_store(path) -> None:
    """A schema 0.1.0 store: consolidated metadata, no index."""
    store = zarr.storage.LocalStore(path)
    root = zarr.open_group(store=store, mode="w")
    root.attrs["mitchell_schema_version"] = "0.1.0"
    grp = root.require_group("events/GW000000/old:analysis")
    grp.attrs["approximant"] = "Old"
    grp.require_group("posterior/samples")["mass_1"] = np.arange(5.0)
    zarr.consolidate_metadata(store)


def test_rebuild_index_upgrades_legacy_store(tmp_path):
    out = tmp_path / "legacy.zarr"
    make_legacy_store(out)
    assert "consolidated_metadata" in root_json(out)

    store = MitchellStore.open(out, mode="r+")
    assert store.schema_version == "0.1.0"
    assert store._index() is None
    assert [e.name for e in store] == ["GW000000"]  # listing still works

    store.rebuild_index()
    root = root_json(out)
    assert root["attributes"]["mitchell_schema_version"] == "0.2.0"
    assert "consolidated_metadata" not in root
    entry = root["attributes"]["mitchell_index"]["events"]["GW000000"]["old:analysis"]
    assert entry["posterior"] == ["mass_1"]
    assert entry["n_samples"] == 5


def test_appending_to_legacy_store_upgrades_it(tmp_path, h5_file):
    out = tmp_path / "legacy.zarr"
    make_legacy_store(out)

    MitchellStore.from_pesummary_h5(h5_file, "GW000001_000000", out)

    store = MitchellStore.open(out, mode="r")
    assert store.schema_version == "0.2.0"
    # The stale consolidated metadata did not hide either event.
    assert [e.name for e in store] == ["GW000000", "GW000001_000000"]
    assert "consolidated_metadata" not in root_json(out)


def test_reindex_cli(tmp_path):
    out = tmp_path / "legacy.zarr"
    make_legacy_store(out)
    result = CliRunner().invoke(cli, ["reindex", str(out)])
    assert result.exit_code == 0, result.output
    assert "schema 0.1.0 -> 0.2.0" in result.output
    assert MitchellStore.open(out, mode="r").schema_version == "0.2.0"
