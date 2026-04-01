# JavaScript / TypeScript

Mitchell ships a universal JavaScript/TypeScript package, `@mitchell/javascript`,
that reads Mitchell zarr v3 stores from both **Node.js** (via the local
filesystem) and the **browser** (via HTTP or S3, with no server required).

The package uses [zarrita](https://github.com/manzt/zarrita.js) as its zarr
backend and is distributed as a dual ESM/CJS bundle with full TypeScript
declarations.

---

## Installation

```bash
npm install @mitchell/javascript
```

---

## Opening a store

### Node.js — local filesystem

```typescript
import { MitchellStore } from "@mitchell/javascript";
import { FileSystemStore } from "@mitchell/javascript/node";

const ms = await MitchellStore.open(new FileSystemStore("/path/to/events.zarr"));
console.log(ms.eventNames());   // ["GW150914_095045", ...]
```

### Browser — HTTP or S3

```typescript
import * as zarrita from "zarrita";
import { MitchellStore } from "@mitchell/javascript";

const ms = await MitchellStore.open(
  new zarrita.FetchStore("https://my-bucket.s3.amazonaws.com/events.zarr")
);
```

No server is required — zarr stores can be read directly from any HTTP origin
or S3 bucket that has CORS enabled.  The store must have consolidated metadata
(written by `zarr.consolidate_metadata()` in Python) so that the full event
and analysis listing is available in a single request.

---

## Navigating the store

Discovery is **synchronous** — event names, analysis names, and data-product
parameter lists are all available immediately after `MitchellStore.open()`
because they come from the consolidated metadata loaded at open time.  Only
actual array data reads are asynchronous.

```typescript
// Synchronous discovery
const eventNames    = ms.eventNames();        // string[]
const event         = await ms.get("GW150914_095045");
const analysisNames = event.analysisNames();  // string[]
const analysis      = await event.get("C01:IMRPhenomXPHM");

// Synchronous data-product presence checks
const paramNames    = analysis.posterior!.parameterNames(); // string[]
const detectors     = analysis.psds!.detectorNames();       // string[]

// Asynchronous data reads
const mass1 = await analysis.posterior!.get("mass_1");        // Float64Array
const h1    = await analysis.psds!.get("H1");                 // { data, shape }
```

Iterate over all events and analyses with `for await`:

```typescript
for await (const event of ms.events()) {
  for await (const analysis of event.analyses()) {
    console.log(event.name, analysis.name);
  }
}
```

---

## Data products

Each {js:class}`Analysis` exposes all data products as synchronous properties
that return `null` when the product was not stored for that analysis.

| Property | Type | Contents |
|---|---|---|
| `posterior` | {js:class}`PosteriorSamples` \| `null` | Columnar float64 posterior draws |
| `priors` | {js:class}`Priors` \| `null` | Sampled and/or analytic prior information |
| `psds` | {js:class}`PSDs` \| `null` | PSD arrays per detector |
| `calibrationEnvelope` | {js:class}`CalibrationEnvelope` \| `null` | Calibration envelopes per detector |
| `skymap` | {js:class}`Skymap` \| `null` | HEALPix pixel data |
| `config` | `Record<string, unknown>` | Config file key-value pairs |

### Posterior samples

```typescript
const post = analysis.posterior!;
const params = post.parameterNames();   // ["mass_1", "mass_2", ...]

// Load one parameter
const mass1: Float64Array = await post.get("mass_1");

// Load all parameters in parallel
const all: Record<string, Float64Array> = await post.getAll();
```

### PSDs

Each PSD is a `(N, 2)` array of `[frequency_Hz, ASD]` columns, returned as a
flat `Float64Array` with shape metadata:

```typescript
const psd = await analysis.psds!.get("H1");
// psd.data   : Float64Array  (length = N * 2, row-major)
// psd.shape  : [N, 2]
```

### Priors

```typescript
const priors = analysis.priors!;
priors.analytic["mass_1"];          // "Uniform(minimum=5, maximum=100)"
priors.hasSamples();                // true / false
const mass1 = await priors.samples!.get("mass_1");
```

### Skymap

```typescript
const sky = analysis.skymap!;
sky.metadata["nside"];              // HEALPix NSIDE parameter
const pixels: Float64Array = await sky.getData();
```

---

## Analysis metadata attributes

The {js:attr}`Analysis.attrs` property gives access to the bilby meta_data
fields promoted when the store was built from an HDF5 file:

```typescript
analysis.attrs.approximant        // "IMRPhenomXPHM"
analysis.attrs.f_low              // 20.0 (Hz)
analysis.attrs.sampling_frequency // 4096.0 (Hz)
```

See {js:class}`AnalysisAttrs` for the full list.

---

## API reference

```{toctree}
:maxdepth: 1

javascript-api
```
