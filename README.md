# mitchell

Mitchell is a next-generation gravitational-wave data library which uses zarr
under the hood to provide cloud-ready, parallelisable access to gravitational
wave analysis data products (posterior samples, normalising flows, PSDs,
skymaps, calibration envelopes, and more).

The cross-language contract is the **zarr v3 store schema** — not a shared
compiled core.  Each language implements the schema independently on top of
its own native zarr backend.

---

## Python

```bash
pip install mitchell
```

```python
import mitchell

store = mitchell.MitchellStore.open("events.zarr")
for event in store:
    for analysis in event:
        mass_1 = analysis.posterior["mass_1"][:]
```

Import from a GWTC bilby HDF5 file:

```bash
mitchell from-bilby-h5 GW150914.h5 GW150914_095045 events.zarr
```

---

## JavaScript / TypeScript

```bash
npm install @mitchell/javascript
```

### Node.js (local filesystem)

```typescript
import { MitchellStore } from "@mitchell/javascript";
import { FileSystemStore } from "@mitchell/javascript/node";

const ms = await MitchellStore.open(new FileSystemStore("events.zarr"));

for await (const event of ms.events()) {
  console.log(event.name);
  for await (const analysis of event.analyses()) {
    const mass1 = await analysis.posterior?.get("mass_1");
  }
}
```

### Browser (HTTP / S3)

```typescript
import * as zarrita from "zarrita";
import { MitchellStore } from "@mitchell/javascript";

const ms = await MitchellStore.open(
  new zarrita.FetchStore("https://my-bucket.s3.amazonaws.com/events.zarr")
);
```

No server required — zarr stores can be read directly from any HTTP origin or
S3 bucket with CORS enabled.

---

## Future language bindings

| Language | Backend | Status |
|----------|---------|--------|
| Python   | zarr-python v3 | stable |
| JavaScript / TypeScript | zarrita | stable |
| Julia | Zarr.jl | planned |
| R | pizzarr | planned |

---

## Development

### Python

```bash
pip install -e ".[dev]"
pytest tests/ -v
ruff check src/ tests/
mypy src/mitchell
```

### JavaScript

```bash
cd bindings/javascript
npm install
python tests/create_fixture.py   # generate test zarr store
npm test
npm run build
```

To regenerate the test fixture after changing `tests/create_fixture.py`:

```bash
python bindings/javascript/tests/create_fixture.py
```

---

## Schema

All language bindings share the same zarr v3 store layout:

```
{root}/
├── zarr.json                           # mitchell_schema_version attribute
└── events/
    └── {event_name}/
        └── {analysis_name}/
            ├── zarr.json               # analysis metadata attributes
            ├── posterior/samples/      # columnar float64 arrays
            ├── priors/
            │   ├── samples/            # columnar float64 arrays
            │   └── analytic/           # prior strings as attributes
            ├── psds/                   # (N, 2) float64 per detector
            ├── calibration_envelope/   # (300, 7) float64 per detector
            ├── skymap/                 # HEALPix float64 data array
            └── config_file/            # INI config as attributes
```

See [docs/schema.md](docs/schema.md) for the full specification.

---

## License

MIT
