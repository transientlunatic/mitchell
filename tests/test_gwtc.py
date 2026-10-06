"""Tests for mitchell.gwtc — the gwresults-driven `from-gwtc` pipeline.

No network calls are made: gwresults' cache.fetch is monkeypatched to
return the local PESummary fixture that ships (gitignored) alongside the
repo, mirroring the pattern the from-pesummary tests already use.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

gwresults = pytest.importorskip("gwresults")

from click.testing import CliRunner  # noqa: E402

from mitchell import MitchellStore  # noqa: E402
from mitchell.cli import cli  # noqa: E402
from mitchell.gwtc import ConversionResult, build_from_gwtc  # noqa: E402

FIXTURE = Path(
    "/home/daniel/repositories/ligo/pe-next/mitchell/mitchell"
    "/IGWN-GWTC2p1-v2-GW150914_095045_PEDataRelease_mixed_cosmo.h5"
)

pytestmark = pytest.mark.skipif(
    not FIXTURE.exists(), reason="HDF5 test fixture not present"
)


@pytest.fixture
def fake_registry(tmp_path, monkeypatch):
    """Serve two fake event names, each backed by a private copy of FIXTURE."""
    copies = {}
    for name in ("GWfake_000000", "GWfake_111111"):
        dest = tmp_path / f"{name}.h5"
        shutil.copy(FIXTURE, dest)
        copies[name] = dest

    monkeypatch.setattr(
        "mitchell.gwtc.iter_gwtc_events", lambda catalogues=None: list(copies)
    )

    def fake_fetch(event: str) -> str:
        if event not in copies:
            raise gwresults.registry.RegistryError(event)
        dest = copies[event]
        if not dest.exists():  # gwtc.py deletes it after each attempt
            shutil.copy(FIXTURE, dest)
        return str(dest)

    monkeypatch.setattr("gwresults.cache.fetch", fake_fetch)
    return copies


class TestBuildFromGwtc:
    def test_converts_all_events(self, fake_registry, tmp_path):
        out = tmp_path / "out.zarr"
        results = list(build_from_gwtc(out))
        assert [r.status for r in results] == ["converted", "converted"]
        store = MitchellStore.open(out, mode="r")
        assert len(store) == 2

    def test_deletes_cache_after_conversion(self, fake_registry, tmp_path):
        out = tmp_path / "out.zarr"
        list(build_from_gwtc(out))
        for path in fake_registry.values():
            assert not path.exists()

    def test_keep_cache_preserves_file(self, fake_registry, tmp_path):
        out = tmp_path / "out.zarr"
        list(build_from_gwtc(out, keep_cache=True))
        for path in fake_registry.values():
            assert path.exists()

    def test_rerun_skips_existing(self, fake_registry, tmp_path):
        out = tmp_path / "out.zarr"
        list(build_from_gwtc(out, keep_cache=True))
        second = list(build_from_gwtc(out, keep_cache=True))
        assert all(r.status == "skipped" for r in second)

    def test_limit_truncates(self, fake_registry, tmp_path):
        out = tmp_path / "out.zarr"
        results = list(build_from_gwtc(out, limit=1))
        assert len(results) == 1

    def test_events_overrides_catalogues(self, fake_registry, tmp_path):
        out = tmp_path / "out.zarr"
        results = list(build_from_gwtc(out, events=["GWfake_000000"]))
        assert [r.event_name for r in results] == ["GWfake_000000"]

    def test_failed_fetch_reported_without_stopping_batch(
        self, fake_registry, tmp_path, monkeypatch
    ):
        monkeypatch.setattr(
            "mitchell.gwtc.iter_gwtc_events",
            lambda catalogues=None: ["GWfake_missing", *fake_registry],
        )
        out = tmp_path / "out.zarr"
        results = list(build_from_gwtc(out))
        statuses = {r.event_name: r.status for r in results}
        assert statuses["GWfake_missing"] == "failed"
        assert statuses["GWfake_000000"] == "converted"
        assert statuses["GWfake_111111"] == "converted"

    def test_failed_convert_reported_without_stopping_batch(
        self, fake_registry, tmp_path, monkeypatch
    ):
        real_from_pesummary_h5 = MitchellStore.from_pesummary_h5

        def flaky(h5_path, event_name, zarr_path, mode="a"):
            if event_name == "GWfake_000000":
                raise ValueError("simulated bad HDF5 layout")
            return real_from_pesummary_h5(h5_path, event_name, zarr_path, mode=mode)

        monkeypatch.setattr(MitchellStore, "from_pesummary_h5", staticmethod(flaky))

        out = tmp_path / "out.zarr"
        results = list(build_from_gwtc(out))
        statuses = {r.event_name: r.status for r in results}
        assert statuses["GWfake_000000"] == "failed"
        assert statuses["GWfake_111111"] == "converted"

    def test_partial_write_on_failure_is_cleaned_up_and_retried(
        self, fake_registry, tmp_path, monkeypatch
    ):
        """A conversion that writes some groups before raising must not be
        left behind as a false "already present" — it should be retried."""
        import zarr

        real_from_pesummary_h5 = MitchellStore.from_pesummary_h5
        attempted: list[str] = []

        def partial_then_fail(h5_path, event_name, zarr_path, mode="a"):
            if event_name == "GWfake_000000" and not attempted:
                attempted.append(event_name)
                store = zarr.storage.LocalStore(zarr_path)
                root = zarr.open_group(store=store, mode="a")
                root.require_group(f"events/{event_name}/some-analysis")
                raise ValueError("simulated crash partway through conversion")
            return real_from_pesummary_h5(h5_path, event_name, zarr_path, mode=mode)

        monkeypatch.setattr(
            MitchellStore, "from_pesummary_h5", staticmethod(partial_then_fail)
        )

        out = tmp_path / "out.zarr"
        first = list(build_from_gwtc(out))
        assert {r.event_name: r.status for r in first}["GWfake_000000"] == "failed"

        store = MitchellStore.open(out, mode="r")
        assert "GWfake_000000" not in store

        second = list(build_from_gwtc(out))
        assert {r.event_name: r.status for r in second}["GWfake_000000"] == "converted"


class TestContains:
    def test_contains_present_event(self, fake_registry, tmp_path):
        out = tmp_path / "out.zarr"
        list(build_from_gwtc(out))
        store = MitchellStore.open(out, mode="r")
        assert "GWfake_000000" in store

    def test_contains_missing_event(self, fake_registry, tmp_path):
        out = tmp_path / "out.zarr"
        list(build_from_gwtc(out))
        store = MitchellStore.open(out, mode="r")
        assert "GWfake_does_not_exist" not in store

    def test_contains_on_empty_store(self, tmp_path):
        out = tmp_path / "empty.zarr"
        store = MitchellStore.open(out, mode="w")
        assert "anything" not in store


class TestCliFromGwtc:
    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_help(self, runner):
        result = runner.invoke(cli, ["from-gwtc", "--help"])
        assert result.exit_code == 0
        assert "ZARR_PATH" in result.output

    def test_runs_and_reports_summary(self, runner, fake_registry, tmp_path):
        out = tmp_path / "out.zarr"
        result = runner.invoke(cli, ["from-gwtc", str(out)])
        assert result.exit_code == 0
        assert "2 converted, 0 skipped, 0 failed" in result.output

    def test_limit_option(self, runner, fake_registry, tmp_path):
        out = tmp_path / "out.zarr"
        result = runner.invoke(cli, ["from-gwtc", str(out), "--limit", "1"])
        assert result.exit_code == 0
        assert "1 converted, 0 skipped, 0 failed" in result.output


def test_conversion_result_defaults():
    result = ConversionResult("GW000000", "converted")
    assert result.detail == ""
