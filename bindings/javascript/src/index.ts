/**
 * @mitchell/javascript — JavaScript/TypeScript bindings for Mitchell zarr stores.
 *
 * Provides cloud-ready, lazy read access to gravitational-wave analysis
 * data products (posterior samples, PSDs, skymaps, …) stored in the
 * Mitchell zarr v3 schema.
 *
 * For Node.js filesystem access import ``FileSystemStore`` from the
 * ``@mitchell/javascript/node`` sub-path export.  For HTTP/cloud access
 * use zarrita's built-in ``FetchStore`` directly.
 *
 * @example
 * ```typescript
 * import { MitchellStore } from "@mitchell/javascript";
 * import { FileSystemStore } from "@mitchell/javascript/node";
 *
 * const ms = await MitchellStore.open(new FileSystemStore("events.zarr"));
 * for await (const event of ms.events()) {
 *   for await (const analysis of event.analyses()) {
 *     const all = await analysis.posterior?.getAll();
 *   }
 * }
 * ```
 *
 * @module
 */

export {
  Analysis,
  CalibrationEnvelope,
  Event,
  MitchellStore,
  PosteriorSamples,
  Priors,
  PSDs,
  Skymap,
} from "./store.js";
export type { Array2D } from "./store.js";
export type { AnalysisAttrs, ArrayChunk, ConsolidatedEntry } from "./types.js";
