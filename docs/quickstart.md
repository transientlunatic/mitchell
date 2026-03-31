# Quickstart

## Installation

```bash
pip install mitchell
```

## Opening an existing store

```python
import mitchell

store = mitchell.MitchellStore.open("path/to/events.zarr")
event = store["GW150914_095045"]
analysis = event["C01:IMRPhenomXPHM"]

# Lazy zarr arrays — nothing loaded until you index
posterior = analysis.posterior
print(posterior["mass_1"][:100])  # first 100 samples
```

## Importing from a bilby HDF5 file

```bash
mitchell from-bilby-h5 GW150914.h5 GW150914_095045 output.zarr
```

Or from Python:

```python
store = mitchell.MitchellStore.from_bilby_h5(
    "GW150914.h5",
    event_name="GW150914_095045",
    zarr_path="output.zarr",
)
```

## ArviZ integration

```python
idata = analysis.to_arviz()
import arviz as az
az.plot_posterior(idata, var_names=["mass_1", "mass_2", "chi_eff"])
```
