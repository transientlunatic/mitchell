import shutil

import numpy as np
import pytest
import zarr
from click.testing import CliRunner

import mitchell
from mitchell import Analysis, Event, MitchellStore
from mitchell.cli import _infer_event_name, cli
from mitchell.store import _decode


def test_version() -> None:
    assert mitchell.__version__ != "0.0.0+unknown"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

N_SAMPLES = 50
PARAMS = ["mass_1", "mass_2", "chi_eff", "luminosity_distance"]
DETECTORS = ["H1", "L1"]
N_PSD = 128


def _make_store(tmp_path) -> MitchellStore:
    """Build a minimal in-memory-style store on disk for testing."""
    rng = np.random.default_rng(42)
    store_path = tmp_path / "test.zarr"
    store = zarr.storage.LocalStore(store_path)
    root = zarr.open_group(store=store, mode="w")
    root.attrs["mitchell_schema_version"] = "0.1.0"

    analysis = root.require_group("events/GW000000/IMRPhenomXPHM")
    analysis.attrs["approximant"] = "IMRPhenomXPHM"
    analysis.attrs["f_low"] = 20.0

    post = analysis.require_group("posterior/samples")
    for p in PARAMS:
        post[p] = rng.standard_normal(N_SAMPLES)

    prior_s = analysis.require_group("priors/samples")
    for p in PARAMS:
        prior_s[p] = rng.standard_normal(N_SAMPLES)

    analytic = analysis.require_group("priors/analytic")
    analytic.attrs["mass_1"] = "Uniform(minimum=5, maximum=100)"

    psds = analysis.require_group("psds")
    for det in DETECTORS:
        psds[det] = rng.random((N_PSD, 2))

    cal = analysis.require_group("calibration_envelope")
    for det in DETECTORS:
        cal[det] = rng.random((300, 7))

    cfg = analysis.require_group("config_file")
    cfg.attrs["sampler"] = "dynesty"
    cfg.attrs["duration"] = "4"

    zarr.consolidate_metadata(store)
    return MitchellStore(store, mode="a")


@pytest.fixture()
def ms(tmp_path):
    return _make_store(tmp_path)


@pytest.fixture()
def analysis(ms) -> Analysis:
    return ms["GW000000"]["IMRPhenomXPHM"]


# ---------------------------------------------------------------------------
# MitchellStore tests
# ---------------------------------------------------------------------------

class TestMitchellStore:
    def test_schema_version_attribute(self, ms):
        assert ms._root.attrs["mitchell_schema_version"] == "0.1.0"

    def test_len(self, ms):
        assert len(ms) == 1

    def test_iter(self, ms):
        events = list(ms)
        assert len(events) == 1
        assert isinstance(events[0], Event)

    def test_getitem(self, ms):
        event = ms["GW000000"]
        assert isinstance(event, Event)

    def test_getitem_missing_raises(self, ms):
        with pytest.raises(KeyError):
            ms["DOESNOTEXIST"]

    def test_open_roundtrip(self, tmp_path):
        store_path = tmp_path / "rt.zarr"
        s = MitchellStore.open(store_path, mode="w")
        s._root.require_group("events/X")
        del s
        reopened = MitchellStore.open(store_path, mode="r")
        assert "events" in reopened._root

    def test_repr(self, ms):
        assert "1 event" in repr(ms)


# ---------------------------------------------------------------------------
# Event tests
# ---------------------------------------------------------------------------

class TestEvent:
    def test_name(self, ms):
        assert ms["GW000000"].name == "GW000000"

    def test_len(self, ms):
        assert len(ms["GW000000"]) == 1

    def test_iter(self, ms):
        analyses = list(ms["GW000000"])
        assert len(analyses) == 1
        assert isinstance(analyses[0], Analysis)

    def test_getitem(self, ms):
        a = ms["GW000000"]["IMRPhenomXPHM"]
        assert isinstance(a, Analysis)

    def test_repr(self, ms):
        assert "GW000000" in repr(ms["GW000000"])


# ---------------------------------------------------------------------------
# Analysis tests
# ---------------------------------------------------------------------------

class TestAnalysis:
    def test_name(self, analysis):
        assert analysis.name == "IMRPhenomXPHM"

    def test_attrs(self, analysis):
        assert analysis.attrs["approximant"] == "IMRPhenomXPHM"
        assert analysis.attrs["f_low"] == 20.0

    def test_posterior_is_group(self, analysis):
        assert analysis.posterior is not None

    def test_posterior_params(self, analysis):
        assert set(PARAMS) == set(analysis.posterior.array_keys())

    def test_posterior_shape(self, analysis):
        for p in PARAMS:
            assert analysis.posterior[p].shape == (N_SAMPLES,)

    def test_priors_samples(self, analysis):
        assert analysis.priors is not None
        assert "samples" in analysis.priors

    def test_priors_analytic_attrs(self, analysis):
        assert "mass_1" in analysis.priors["analytic"].attrs

    def test_psds(self, analysis):
        assert analysis.psds is not None
        for det in DETECTORS:
            assert analysis.psds[det].shape == (N_PSD, 2)

    def test_calibration_envelope(self, analysis):
        assert analysis.calibration_envelope is not None
        for det in DETECTORS:
            assert analysis.calibration_envelope[det].shape == (300, 7)

    def test_config(self, analysis):
        cfg = analysis.config
        assert cfg["sampler"] == "dynesty"

    def test_no_skymap_returns_none(self, analysis):
        assert analysis.skymap is None

    def test_repr(self, analysis):
        assert "IMRPhenomXPHM" in repr(analysis)


# ---------------------------------------------------------------------------
# ArviZ conversion tests
# ---------------------------------------------------------------------------

class TestToArviz:
    def test_returns_inference_data(self, analysis):
        pytest.importorskip("arviz")
        idata = analysis.to_arviz()
        assert idata is not None

    def test_posterior_group_present(self, analysis):
        pytest.importorskip("arviz")
        idata = analysis.to_arviz()
        assert hasattr(idata, "posterior")

    def test_posterior_variables(self, analysis):
        pytest.importorskip("arviz")
        idata = analysis.to_arviz()
        for p in PARAMS:
            assert p in idata.posterior

    def test_posterior_shape(self, analysis):
        pytest.importorskip("arviz")
        idata = analysis.to_arviz()
        # ArviZ shape: (chain=1, draw=N_SAMPLES)
        assert idata.posterior["mass_1"].shape == (1, N_SAMPLES)

    def test_prior_group_present(self, analysis):
        pytest.importorskip("arviz")
        idata = analysis.to_arviz()
        assert hasattr(idata, "prior")

    def test_prior_variables(self, analysis):
        pytest.importorskip("arviz")
        idata = analysis.to_arviz()
        for p in PARAMS:
            assert p in idata.prior


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

@pytest.fixture()
def runner():
    return CliRunner()


class TestCli:
    def test_help(self, runner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Mitchell" in result.output

    def test_version(self, runner):
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert mitchell.__version__ in result.output

    def test_from_pesummary_help(self, runner):
        result = runner.invoke(cli, ["from-pesummary", "--help"])
        assert result.exit_code == 0
        assert "H5_PATH" in result.output
        assert "ZARR_PATH" in result.output

    def test_from_pesummary_missing_args(self, runner):
        result = runner.invoke(cli, ["from-pesummary"])
        assert result.exit_code != 0

    def test_from_pesummary_bad_h5_path(self, runner, tmp_path):
        result = runner.invoke(
            cli,
            ["from-pesummary", "nonexistent.h5", str(tmp_path / "out.zarr")],
        )
        assert result.exit_code != 0

    def test_from_pesummary_runs(self, runner, tmp_path):
        """End-to-end single-file conversion with explicit event name."""
        h5_path = (
            "/home/daniel/repositories/ligo/pe-next/mitchell/mitchell"
            "/IGWN-GWTC2p1-v2-GW150914_095045_PEDataRelease_mixed_cosmo.h5"
        )
        pytest.importorskip("h5py")
        if not __import__("pathlib").Path(h5_path).exists():
            pytest.skip("HDF5 test file not present")
        out = tmp_path / "out.zarr"
        result = runner.invoke(
            cli,
            ["from-pesummary", h5_path, str(out), "--event-name", "GW150914_095045"],
        )
        assert result.exit_code == 0
        assert "Done." in result.output
        store = MitchellStore.open(out, mode="r")
        assert len(store) == 1

    def test_from_pesummary_infers_event_name(self, runner, tmp_path):
        """Event name is inferred from the GWTC filename when not given."""
        h5_path = (
            "/home/daniel/repositories/ligo/pe-next/mitchell/mitchell"
            "/IGWN-GWTC2p1-v2-GW150914_095045_PEDataRelease_mixed_cosmo.h5"
        )
        pytest.importorskip("h5py")
        if not __import__("pathlib").Path(h5_path).exists():
            pytest.skip("HDF5 test file not present")
        out = tmp_path / "out.zarr"
        result = runner.invoke(cli, ["from-pesummary", h5_path, str(out)])
        assert result.exit_code == 0
        store = MitchellStore.open(out, mode="r")
        assert store["GW150914_095045"] is not None

    def test_from_pesummary_append(self, runner, tmp_path):
        """Running twice with different event names appends to the same store."""
        pytest.importorskip("h5py")
        h5_path = (
            "/home/daniel/repositories/ligo/pe-next/mitchell/mitchell"
            "/IGWN-GWTC2p1-v2-GW150914_095045_PEDataRelease_mixed_cosmo.h5"
        )
        if not __import__("pathlib").Path(h5_path).exists():
            pytest.skip("HDF5 test file not present")
        out = tmp_path / "out.zarr"
        runner.invoke(
            cli,
            ["from-pesummary", h5_path, str(out), "--event-name", "GW150914_095045"],
        )
        runner.invoke(
            cli,
            ["from-pesummary", h5_path, str(out), "--event-name", "GW150914_copy"],
        )
        store = MitchellStore.open(out, mode="r")
        assert len(store) == 2

    def test_from_pesummary_overwrite(self, runner, tmp_path):
        """--overwrite replaces an existing store rather than appending."""
        pytest.importorskip("h5py")
        h5_path = (
            "/home/daniel/repositories/ligo/pe-next/mitchell/mitchell"
            "/IGWN-GWTC2p1-v2-GW150914_095045_PEDataRelease_mixed_cosmo.h5"
        )
        if not __import__("pathlib").Path(h5_path).exists():
            pytest.skip("HDF5 test file not present")
        out = tmp_path / "out.zarr"
        runner.invoke(
            cli,
            ["from-pesummary", h5_path, str(out), "--event-name", "GW150914_095045"],
        )
        result = runner.invoke(
            cli,
            [
                "from-pesummary", "--overwrite", h5_path, str(out),
                "--event-name", "GW150914_095045",
            ],
        )
        assert result.exit_code == 0
        store = MitchellStore.open(out, mode="r")
        assert len(store) == 1

    def test_from_pesummary_directory(self, runner, tmp_path):
        """A directory of .h5 files is batch-converted into a single store."""
        h5_path = __import__("pathlib").Path(
            "/home/daniel/repositories/ligo/pe-next/mitchell/mitchell"
            "/IGWN-GWTC2p1-v2-GW150914_095045_PEDataRelease_mixed_cosmo.h5"
        )
        pytest.importorskip("h5py")
        if not h5_path.exists():
            pytest.skip("HDF5 test file not present")
        src_dir = tmp_path / "metafiles"
        src_dir.mkdir()
        shutil.copy(h5_path, src_dir / h5_path.name)
        shutil.copy(
            h5_path,
            src_dir / "IGWN-GWTC2p1-v2-GW151226_033853_PEDataRelease_mixed_cosmo.h5",
        )
        out = tmp_path / "out.zarr"
        result = runner.invoke(cli, ["from-pesummary", str(src_dir), str(out)])
        assert result.exit_code == 0
        store = MitchellStore.open(out, mode="r")
        assert len(store) == 2

    def test_from_pesummary_directory_rejects_event_name(self, runner, tmp_path):
        """--event-name together with a directory is an error."""
        src_dir = tmp_path / "metafiles"
        src_dir.mkdir()
        out = tmp_path / "out.zarr"
        result = runner.invoke(
            cli,
            [
                "from-pesummary", str(src_dir), str(out),
                "--event-name", "GW150914_095045",
            ],
        )
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Event name inference unit tests
# ---------------------------------------------------------------------------

class TestDecode:
    def test_unwraps_length_one_array(self):
        assert _decode(np.array([3.5])) == 3.5

    def test_decodes_bytes(self):
        assert _decode(b"hello") == "hello"

    def test_converts_numpy_int_to_native(self):
        result = _decode(np.int64(7))
        assert result == 7
        assert type(result) is int

    def test_converts_numpy_bool_to_native(self):
        result = _decode(np.bool_(True))
        assert result is True

    def test_numpy_int_is_json_serializable_after_decode(self):
        import json

        json.dumps(_decode(np.int64(7)))

    def test_leaves_plain_values_untouched(self):
        assert _decode(3.5) == 3.5
        assert _decode("already a string") == "already a string"


class TestInferEventName:
    def test_standard_gwtc_filename(self, tmp_path):
        p = tmp_path / "IGWN-GWTC2p1-v2-GW150914_095045_PEDataRelease_mixed_cosmo.h5"
        assert _infer_event_name(p) == "GW150914_095045"

    def test_minimal_filename(self, tmp_path):
        p = tmp_path / "GW200105_162426.h5"
        assert _infer_event_name(p) == "GW200105_162426"

    def test_no_gw_pattern_raises(self, tmp_path):
        import click
        p = tmp_path / "some_random_file.h5"
        with pytest.raises(click.BadParameter):
            _infer_event_name(p)

