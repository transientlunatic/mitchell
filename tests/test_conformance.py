"""Read the shared conformance fixture through the Python API.

The same fixture (``tests/conformance/store.zarr``) and expectations
(``expected.json``) are checked by every language binding.
"""

import json
from pathlib import Path

import numpy as np
import pytest

from mitchell import MitchellStore

CONFORMANCE = Path(__file__).parent / "conformance"
EXPECTED = json.loads((CONFORMANCE / "expected.json").read_text())


def _check(arr, exp) -> None:
    arr = np.asarray(arr)
    assert list(arr.shape) == exp["shape"]
    flat = arr.ravel()
    np.testing.assert_allclose(flat[: len(exp["head"])], exp["head"], rtol=1e-12)
    np.testing.assert_allclose(flat.sum(), exp["sum"], rtol=1e-9)


@pytest.fixture(scope="module")
def store() -> MitchellStore:
    return MitchellStore.open(CONFORMANCE / "store.zarr", mode="r")


def test_events(store) -> None:
    assert sorted(e.name for e in store) == sorted(EXPECTED["events"])
    assert store._root.attrs["mitchell_schema_version"] == EXPECTED["schema_version"]


@pytest.mark.parametrize(
    ("event", "analysis"),
    [(e, a) for e, d in EXPECTED["events"].items() for a in d],
)
def test_analysis(store, event, analysis) -> None:
    exp = EXPECTED["events"][event][analysis]
    a = store[event][analysis]

    assert dict(a.attrs) == exp["attrs"]
    for name, e in exp["posterior"].items():
        _check(a.posterior[name][:], e)
    for name, e in exp["prior_samples"].items():
        _check(a.priors["samples"][name][:], e)
    assert dict(a.priors["analytic"].attrs) == exp["prior_analytic"]
    for det, e in exp["psds"].items():
        _check(a.psds[det][:], e)
    for det, e in exp["calibration_envelope"].items():
        _check(a.calibration_envelope[det][:], e)
    assert dict(a.skymap.attrs) == exp["skymap"]["attrs"]
    _check(a.skymap["data"][:], exp["skymap"]["data"])
    assert a.config == exp["config"]
