"""Regenerate the cross-language conformance fixture.

Writes ``store.zarr`` (a tiny Mitchell store) and ``expected.json`` (what every
language binding must read back from it) next to this script::

    python tests/conformance/make_fixture.py

Every binding's test suite reads these two files, so a change to the schema
that breaks any reader shows up as a failing test.  Re-run this script (and
commit the output) only when the schema deliberately changes.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import numpy as np
import zarr

HERE = Path(__file__).parent
STORE = HERE / "store.zarr"
EXPECTED = HERE / "expected.json"

N_SAMPLES = 64
NSIDE = 2  # 12 * nside**2 = 48 pixels
POSTERIOR = ["mass_1", "mass_2", "chi_eff", "luminosity_distance"]


def _summary(arr: np.ndarray) -> dict:
    flat = arr.ravel()
    return {
        "shape": list(arr.shape),
        "head": flat[:4].tolist(),
        "sum": float(flat.sum()),
    }


def build() -> dict:
    rng = np.random.default_rng(20150914)
    if STORE.exists():
        shutil.rmtree(STORE)
    root = zarr.open_group(store=zarr.storage.LocalStore(STORE), mode="w")
    root.attrs["mitchell_schema_version"] = "0.1.0"

    expected: dict = {"schema_version": "0.1.0", "events": {}}

    # Two events; the first has two analyses, the second just one.
    layout = {
        "GW150914_095045": ["C01:IMRPhenomXPHM", "C01:SEOBNRv4PHM"],
        "GW170817_124104": ["C01:IMRPhenomD_NRTidalv2"],
    }
    for event_name, analyses in layout.items():
        exp_event: dict = {}
        for k, analysis_name in enumerate(analyses):
            grp = root.require_group(f"events/{event_name}/{analysis_name}")
            attrs = {
                "approximant": analysis_name.split(":")[1],
                "f_low": 20.0,
                "f_ref": 20.0,
                "sampling_frequency": 2048,
                "time_marginalization": bool(k % 2),
                "reference_frame": "H1L1",
            }
            grp.attrs.update(attrs)
            exp: dict = {"attrs": attrs, "posterior": {}}

            post = grp.require_group("posterior/samples")
            for p in POSTERIOR:
                data = rng.standard_normal(N_SAMPLES)
                post[p] = data
                exp["posterior"][p] = _summary(data)

            prior = grp.require_group("priors/samples")
            exp["prior_samples"] = {}
            for p in POSTERIOR[:2]:
                data = rng.uniform(5, 100, N_SAMPLES)
                prior[p] = data
                exp["prior_samples"][p] = _summary(data)
            analytic = {"mass_1": "Uniform(minimum=5, maximum=100)"}
            grp.require_group("priors/analytic").attrs.update(analytic)
            exp["prior_analytic"] = analytic

            exp["psds"] = {}
            psds = grp.require_group("psds")
            for det in ("H1", "L1"):
                data = rng.random((32, 2))
                psds[det] = data
                exp["psds"][det] = _summary(data)

            exp["calibration_envelope"] = {}
            cal = grp.require_group("calibration_envelope")
            for det in ("H1", "L1"):
                data = rng.random((300, 7))
                cal[det] = data
                exp["calibration_envelope"][det] = _summary(data)

            sky = grp.require_group("skymap")
            sky_attrs = {"nside": NSIDE, "ordering": "NESTED"}
            sky.attrs.update(sky_attrs)
            pix = rng.random(12 * NSIDE**2)
            pix /= pix.sum()
            sky["data"] = pix
            exp["skymap"] = {"attrs": sky_attrs, "data": _summary(pix)}

            cfg = {"sampler": "dynesty", "nlive": 1000}
            grp.require_group("config_file").attrs.update(cfg)
            exp["config"] = cfg

            exp_event[analysis_name] = exp
        expected["events"][event_name] = exp_event

    zarr.consolidate_metadata(root.store)
    return expected


if __name__ == "__main__":
    EXPECTED.write_text(json.dumps(build(), indent=2) + "\n")
    print(f"wrote {STORE} and {EXPECTED}")
