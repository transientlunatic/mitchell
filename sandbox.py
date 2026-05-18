# This is just a scratchpad to try playing around with zarr and other things

import h5py as h5
import numpy as np
import zarr

H5_PATH = "IGWN-GWTC2p1-v2-GW150914_095045_PEDataRelease_mixed_cosmo.h5"
EVENT_NAME = "GW150914_095045"
ZARR_PATH = "zarr_test/events.zarr"

# Key meta_data fields to promote to zarr group attributes
META_ATTRS = [
    "approximant", "cosmology", "delta_f", "distance_marginalization",
    "duration", "f_final", "f_low", "f_ref", "phase_marginalization",
    "reference_frame", "sampling_frequency", "start_time",
    "time_marginalization", "time_reference",
]


def _decode(val):
    """Unwrap length-1 arrays and decode byte strings for zarr attributes."""
    if isinstance(val, np.ndarray) and val.ndim == 1 and len(val) == 1:
        val = val[0]
    if isinstance(val, (bytes, np.bytes_)):
        val = val.decode()
    return val


def translate_metafile_to_zarr(h5_path: str, event_name: str, zarr_path: str) -> None:
    store = zarr.storage.LocalStore(zarr_path)
    root = zarr.open_group(store=store, mode="w")
    root.attrs["mitchell_schema_version"] = "0.1.0"
    event = root.require_group(f"events/{event_name}")

    with h5.File(h5_path, "r") as f:
        for analysis_name, h5_group in f.items():

            analysis = event.require_group(analysis_name)

            # --- attributes from meta_data/meta_data ---
            if "meta_data" in h5_group and "meta_data" in h5_group["meta_data"]:
                md = h5_group["meta_data"]["meta_data"]
                analysis.attrs.update(
                    {k: _decode(md[k][()]) for k in META_ATTRS if k in md}
                )

            # version and description as attributes
            if "version" in h5_group:
                analysis.attrs["version"] = _decode(h5_group["version"][()])
            if "description" in h5_group:
                analysis.attrs["description"] = _decode(h5_group["description"][()])

            # --- posterior samples: structured array → columnar arrays ---
            if "posterior_samples" in h5_group:
                samples = h5_group["posterior_samples"][()]
                post_group = analysis.require_group("posterior/samples")
                for param in samples.dtype.names:
                    post_group[param] = samples[param]

            # --- prior samples: already columnar in HDF5 ---
            if "priors" in h5_group:
                priors = h5_group["priors"]

                if "samples" in priors:
                    prior_samples = analysis.require_group("priors/samples")
                    for param, dataset in priors["samples"].items():
                        prior_samples[param] = dataset[()]

                # analytic prior strings stored as group attributes
                if "analytic" in priors and len(priors["analytic"]) > 0:
                    analytic_group = analysis.require_group("priors/analytic")
                    analytic_group.attrs.update(
                        {k: _decode(v[()]) for k, v in priors["analytic"].items()
                         if isinstance(v, h5.Dataset)}
                    )

            # --- PSDs: (N, 2) array per detector [frequency, psd] ---
            if "psds" in h5_group:
                psds_group = analysis.require_group("psds")
                for detector, dataset in h5_group["psds"].items():
                    psds_group[detector] = dataset[()]

            # --- calibration envelope: (N, 7) per detector ---
            if "calibration_envelope" in h5_group:
                cal_group = analysis.require_group("calibration_envelope")
                for detector, dataset in h5_group["calibration_envelope"].items():
                    cal_group[detector] = dataset[()]

            # --- config file: all key=value pairs as group attributes ---
            if "config_file" in h5_group and "config" in h5_group["config_file"]:
                config_group = analysis.require_group("config_file")
                config_group.attrs.update(
                    {k: _decode(v[()]) for k, v in h5_group["config_file"]["config"].items()
                     if isinstance(v, h5.Dataset)}
                )

            # --- skymap: HEALPix data array + metadata attributes ---
            if "skymap" in h5_group:
                skymap_group = analysis.require_group("skymap")
                skymap_h5 = h5_group["skymap"]
                if "data" in skymap_h5:
                    skymap_group["data"] = skymap_h5["data"][()]
                if "meta_data" in skymap_h5:
                    skymap_group.attrs.update(
                        {k: _decode(v[()]) for k, v in skymap_h5["meta_data"].items()
                         if isinstance(v, h5.Dataset)}
                    )

    zarr.consolidate_metadata(store)
    print(root.tree())


translate_metafile_to_zarr(H5_PATH, EVENT_NAME, ZARR_PATH)
