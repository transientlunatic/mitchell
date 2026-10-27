# @mitchell/javascript

TypeScript/JavaScript reader for [Mitchell](../../README.md) zarr v3 stores,
built on [zarrita](https://github.com/manzt/zarrita.js).  It implements the
store schema in `docs/schema.md` independently of the Python package.

```bash
npm install
npm run typecheck && npm test   # tests read ../../tests/conformance
npm run build                   # → dist/ (ESM + CJS + .d.ts)
```

```ts
import * as zarrita from "zarrita";
import { MitchellStore } from "@mitchell/javascript";

const ms = await MitchellStore.open(new zarrita.FetchStore(url));
const event = await ms.get(ms.eventNames()[0]);
const analysis = await event.get(event.analysisNames()[0]);
const mass1 = await analysis.posterior!.get("mass_1");
```

In Node, `import { FileSystemStore } from "@mitchell/javascript/node"` opens a
local store.  It lives in a separate entry point so browser bundles never
import Node built-ins.

## Conformance

`tests/conformance.test.ts` reads the shared fixture in `tests/conformance/`
and checks it against `expected.json`; the Python suite does the same in
`tests/test_conformance.py`.  If you change the schema, regenerate the fixture
with `python tests/conformance/make_fixture.py` and update every binding.
