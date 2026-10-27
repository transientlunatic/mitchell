"""A synthetic PESummary-style metafile shared by the conversion tests."""

import h5py
import numpy as np

DETECTORS = ("H1", "L1")


def make_pesummary_h5(
    path, analyses=("C01:IMRPhenomXPHM", "C01:SEOBNRv4PHM"), n_samples=40, nside=2
):
    """Write a small file with the layout ``from_pesummary_h5`` reads."""
    rng = np.random.default_rng(1)
    with h5py.File(path, "w") as f:
        # File-level groups that PESummary writes next to the analyses.
        f["history/program"] = np.bytes_("summarypages")
        f["version/pesummary"] = np.bytes_("1.0")
        for name in analyses:
            g = f.create_group(name)
            md = g.create_group("meta_data/meta_data")
            md["approximant"] = np.bytes_(name.split(":")[1])
            md["f_low"] = np.array([20.0])
            g["version"] = np.bytes_("1.0")
            g["description"] = np.bytes_("test run")

            dtype = [("mass_1", "f8"), ("mass_2", "f8"), ("chi_eff", "f8")]
            samples = np.zeros(n_samples, dtype=dtype)
            for k in samples.dtype.names:
                samples[k] = rng.standard_normal(n_samples)
            g["posterior_samples"] = samples

            g["priors/samples/mass_1"] = rng.random(n_samples)
            g["priors/analytic/mass_1"] = np.bytes_("Uniform(5, 100)")

            for det in DETECTORS:
                g[f"psds/{det}"] = rng.random((16, 2))
                g[f"calibration_envelope/{det}"] = rng.random((300, 7))

            g["config_file/config/sampler"] = np.bytes_("dynesty")

            pix = rng.random(12 * nside**2)
            g["skymap/data"] = pix / pix.sum()
            g["skymap/meta_data/nside"] = np.array([nside])
            g["skymap/meta_data/nest"] = np.array([b"True"])
