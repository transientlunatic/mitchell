"""Generate the canonical test fixture for the JavaScript binding tests.

Run from the bindings/javascript/ directory:

    python tests/create_fixture.py

This produces tests/fixture/ — a Mitchell-format zarr v3 store that the
TypeScript tests load.  Mirrors the Python test suite's ``_make_store``
helper so that both test suites exercise the same schema content.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import zarr

FIXTURE_PATH = Path(__file__).parent / "fixture"

N_SAMPLES = 50
PARAMS = ["mass_1", "mass_2", "chi_eff", "luminosity_distance"]
DETECTORS = ["H1", "L1"]
N_PSD = 128


def build() -> None:
    if FIXTURE_PATH.exists():
        shutil.rmtree(FIXTURE_PATH)

    rng = np.random.default_rng(42)
    store = zarr.storage.LocalStore(FIXTURE_PATH)
    root = zarr.open_group(store=store, mode="w")
    root.attrs["mitchell_schema_version"] = "0.1.0"

    analysis = root.require_group("events/GW000000/IMRPhenomXPHM")
    analysis.attrs["approximant"] = "IMRPhenomXPHM"
    analysis.attrs["f_low"] = 20.0

    # Posterior samples
    post = analysis.require_group("posterior/samples")
    for p in PARAMS:
        post[p] = rng.standard_normal(N_SAMPLES)

    # Prior samples
    prior_s = analysis.require_group("priors/samples")
    for p in PARAMS:
        prior_s[p] = rng.standard_normal(N_SAMPLES)

    # Analytic priors
    analytic = analysis.require_group("priors/analytic")
    analytic.attrs["mass_1"] = "Uniform(minimum=5, maximum=100)"
    analytic.attrs["mass_2"] = "Uniform(minimum=5, maximum=100)"

    # PSDs: shape (N_PSD, 2) — [frequency, ASD]
    psds = analysis.require_group("psds")
    for det in DETECTORS:
        psds[det] = rng.random((N_PSD, 2))

    # Calibration envelopes: shape (300, 7)
    cal = analysis.require_group("calibration_envelope")
    for det in DETECTORS:
        cal[det] = rng.random((300, 7))

    # Config file
    cfg = analysis.require_group("config_file")
    cfg.attrs["sampler"] = "dynesty"
    cfg.attrs["duration"] = "4"

    # No skymap in the primary analysis — tests the null case

    # Second analysis: minimal, but includes a skymap
    analysis2 = root.require_group("events/GW000000/NRSur7dq4")
    analysis2.attrs["approximant"] = "NRSur7dq4"
    skymap_grp = analysis2.require_group("skymap")
    skymap_grp.attrs["nside"] = 512
    # HEALPix NSIDE=4 has 192 pixels — use a small value for the test fixture
    skymap_grp["data"] = rng.random(192)

    zarr.consolidate_metadata(store)
    print(f"Fixture written to {FIXTURE_PATH}")


if __name__ == "__main__":
    build()
