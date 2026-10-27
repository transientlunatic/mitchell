"""MitchellStore.merge: assemble a catalogue from independently built stores."""

import json

import numpy as np
import pytest
from pesummary_h5 import make_pesummary_h5
from test_index import make_legacy_store, root_json

from mitchell import MitchellStore

EVENTS = ["GW000001_000000", "GW000002_000000", "GW000003_000000"]


@pytest.fixture
def h5_file(tmp_path):
    path = tmp_path / "meta.h5"
    make_pesummary_h5(path)
    return path


@pytest.fixture
def parts(tmp_path, h5_file):
    """One single-event store per event, as parallel jobs would write them."""
    paths = []
    for name in EVENTS:
        path = tmp_path / "parts" / f"{name}.zarr"
        MitchellStore.from_pesummary_h5(h5_file, name, path, mode="w")
        paths.append(path)
    return paths


@pytest.fixture
def sequential(tmp_path, h5_file):
    """The same catalogue built the slow way, event by event into one store."""
    path = tmp_path / "sequential.zarr"
    for name in EVENTS:
        MitchellStore.from_pesummary_h5(h5_file, name, path, mode="a")
    return MitchellStore.open(path, mode="r")


def test_merge_matches_a_sequential_build(tmp_path, parts, sequential):
    out = MitchellStore.open(tmp_path / "catalogue.zarr")
    result = out.merge(parts)

    assert result.added == EVENTS
    assert result.skipped == result.replaced == []
    merged = MitchellStore.open(tmp_path / "catalogue.zarr", mode="r")
    assert merged._index() == sequential._index()
    assert [e.name for e in merged] == EVENTS
    for name in EVENTS:
        for analysis in sequential[name]:
            theirs = merged[name][analysis.name]
            for param in analysis.posterior.array_keys():
                np.testing.assert_array_equal(
                    theirs.posterior[param][:], analysis.posterior[param][:]
                )
            assert dict(theirs.attrs) == dict(analysis.attrs)


def test_merge_copies_by_default(tmp_path, parts):
    MitchellStore.open(tmp_path / "catalogue.zarr").merge(parts)
    assert all(p.exists() for p in parts)


def test_merge_move_consumes_the_parts(tmp_path, parts, sequential):
    out = MitchellStore.open(tmp_path / "catalogue.zarr")
    out.merge(parts, move=True)
    assert not any(p.exists() for p in parts)
    merged = MitchellStore.open(tmp_path / "catalogue.zarr", mode="r")
    assert merged._index() == sequential._index()
    assert merged["GW000001_000000"]["C01:IMRPhenomXPHM"].posterior["mass_1"].shape == (
        40,
    )


def test_merge_skips_events_already_present(tmp_path, parts):
    out = MitchellStore.open(tmp_path / "catalogue.zarr")
    out.merge(parts[:2])
    result = out.merge(parts, move=True)

    assert result.added == [EVENTS[2]]
    assert result.skipped == EVENTS[:2]
    # Parts whose events were all merged are consumed; those with skipped
    # events are left alone.
    assert not parts[2].exists()
    assert parts[0].exists()
    assert parts[1].exists()


def test_merge_replace_overwrites(tmp_path, parts, h5_file):
    out = MitchellStore.open(tmp_path / "catalogue.zarr")
    out.merge(parts)
    bigger = tmp_path / "bigger.h5"
    make_pesummary_h5(bigger, n_samples=70)
    replacement = tmp_path / "replacement.zarr"
    MitchellStore.from_pesummary_h5(bigger, EVENTS[0], replacement, mode="w")

    result = out.merge([replacement], on_conflict="replace")

    assert result.replaced == [EVENTS[0]]
    reopened = MitchellStore.open(tmp_path / "catalogue.zarr", mode="r")
    entry = reopened._index()["events"][EVENTS[0]]["C01:IMRPhenomXPHM"]
    assert entry["n_samples"] == 70
    assert reopened[EVENTS[0]]["C01:IMRPhenomXPHM"].posterior["mass_1"].shape == (70,)


def test_merge_error_changes_nothing(tmp_path, parts):
    out = MitchellStore.open(tmp_path / "catalogue.zarr")
    out.merge(parts[:1])
    before = root_json(tmp_path / "catalogue.zarr")

    with pytest.raises(ValueError, match="already in the store"):
        out.merge(parts, on_conflict="error")

    assert root_json(tmp_path / "catalogue.zarr") == before
    assert not (tmp_path / "catalogue.zarr" / "events" / EVENTS[1]).exists()


def test_merge_writes_a_valid_index_in_one_piece(tmp_path, parts):
    MitchellStore.open(tmp_path / "catalogue.zarr").merge(parts)
    root = root_json(tmp_path / "catalogue.zarr")
    assert list(root["attributes"]["mitchell_index"]["events"]) == EVENTS
    assert "consolidated_metadata" not in root
    json.dumps(root)  # serialisable


def test_merge_into_a_legacy_store_upgrades_it(tmp_path, parts):
    legacy = tmp_path / "legacy.zarr"
    make_legacy_store(legacy)
    out = MitchellStore.open(legacy, mode="r+")

    out.merge(parts)

    merged = MitchellStore.open(legacy, mode="r")
    assert merged.schema_version == "0.2.0"
    assert [e.name for e in merged] == ["GW000000", *EVENTS]
    assert "consolidated_metadata" not in root_json(legacy)


def test_merge_accepts_a_legacy_part(tmp_path):
    legacy = tmp_path / "legacy.zarr"
    make_legacy_store(legacy)
    out = MitchellStore.open(tmp_path / "catalogue.zarr")

    out.merge([legacy])

    entry = out._index()["events"]["GW000000"]["old:analysis"]
    assert entry["posterior"] == ["mass_1"]


def test_merge_rejects_something_that_is_not_a_store(tmp_path):
    (tmp_path / "junk").mkdir()
    out = MitchellStore.open(tmp_path / "catalogue.zarr")
    with pytest.raises(ValueError, match="not a Mitchell store"):
        out.merge([tmp_path / "junk"])
    with pytest.raises(ValueError, match="not a Mitchell store"):
        out.merge([tmp_path / "missing.zarr"])
