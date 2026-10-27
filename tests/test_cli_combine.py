"""`mitchell combine`, and the exit status of `mitchell from-gwtc`."""

import sys
import types

import pytest
from click.testing import CliRunner
from pesummary_h5 import make_pesummary_h5

from mitchell import MitchellStore
from mitchell.cli import cli
from mitchell.gwtc import ConversionResult

EVENTS = ["GW000001_000000", "GW000002_000000"]


@pytest.fixture
def parts_dir(tmp_path):
    h5 = tmp_path / "meta.h5"
    make_pesummary_h5(h5)
    root = tmp_path / "parts"
    for name in EVENTS:
        MitchellStore.from_pesummary_h5(h5, name, root / f"{name}.zarr", mode="w")
    (root / "notes.txt").write_text("not a part")
    return root


def run(*args):
    return CliRunner().invoke(cli, [str(a) for a in args])


def test_combine_parts_dir(tmp_path, parts_dir):
    out = tmp_path / "catalogue.zarr"
    result = run("combine", out, "--parts-dir", parts_dir)
    assert result.exit_code == 0, result.output
    assert "Added 2 event(s)" in result.output
    assert [e.name for e in MitchellStore.open(out, mode="r")] == EVENTS


def test_combine_explicit_parts_and_move(tmp_path, parts_dir):
    out = tmp_path / "catalogue.zarr"
    part = parts_dir / f"{EVENTS[0]}.zarr"
    result = run("combine", out, part, "--move")
    assert result.exit_code == 0, result.output
    assert not part.exists()
    assert [e.name for e in MitchellStore.open(out, mode="r")] == EVENTS[:1]


def test_combine_rerun_skips(tmp_path, parts_dir):
    out = tmp_path / "catalogue.zarr"
    run("combine", out, "--parts-dir", parts_dir)
    result = run("combine", out, "--parts-dir", parts_dir)
    assert result.exit_code == 0
    assert "Added 0 event(s)" in result.output
    assert "skipped 2" in result.output


def test_combine_error_policy_fails(tmp_path, parts_dir):
    out = tmp_path / "catalogue.zarr"
    run("combine", out, "--parts-dir", parts_dir)
    result = run("combine", out, "--parts-dir", parts_dir, "--on-conflict", "error")
    assert result.exit_code != 0
    assert "already in the store" in result.output


def test_combine_needs_parts(tmp_path):
    result = run("combine", tmp_path / "catalogue.zarr")
    assert result.exit_code != 0
    assert "No parts" in result.output


def test_combine_empty_parts_dir(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    result = run("combine", tmp_path / "catalogue.zarr", "--parts-dir", empty)
    assert result.exit_code != 0
    assert "No parts" in result.output


@pytest.fixture
def stub_gwresults(monkeypatch):
    """A stand-in gwresults, so these run without the optional dependency."""
    monkeypatch.setitem(sys.modules, "gwresults", types.ModuleType("gwresults"))


def fake_build(*statuses):
    def build(zarr_path, **kwargs):
        yield from (ConversionResult(f"GWfake_{i}", s) for i, s in enumerate(statuses))

    return build


def test_from_gwtc_exits_nonzero_when_an_event_fails(
    tmp_path, stub_gwresults, monkeypatch
):
    """A scheduler (a Condor DAG, say) retries on failure only if it sees one."""
    monkeypatch.setattr(
        "mitchell.gwtc.build_from_gwtc", fake_build("converted", "failed", "converted")
    )
    result = run("from-gwtc", tmp_path / "out.zarr")
    assert result.exit_code == 1
    assert "2 converted, 0 skipped, 1 failed" in result.output  # the batch finished
    assert "1 event(s) failed" in result.output


def test_from_gwtc_exits_zero_when_all_succeed(tmp_path, stub_gwresults, monkeypatch):
    monkeypatch.setattr(
        "mitchell.gwtc.build_from_gwtc", fake_build("converted", "skipped")
    )
    result = run("from-gwtc", tmp_path / "out.zarr")
    assert result.exit_code == 0, result.output
