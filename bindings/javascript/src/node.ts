/**
 * Node.js-specific store for Mitchell.
 *
 * Re-exports {@link https://github.com/manzt/zarrita.js @zarrita/storage}'s
 * built-in ``FileSystemStore``, which reads zarr v3 stores from the local
 * filesystem with correct handling of the full zarrita store contract
 * (range requests, absolute paths, etc.).
 *
 * Import this sub-path in Node.js environments only — it is not usable
 * in browsers.  For HTTP/S3 access use zarrita's ``FetchStore`` instead.
 *
 * @example
 * ```typescript
 * import { FileSystemStore } from "@mitchell/javascript/node";
 * import { MitchellStore } from "@mitchell/javascript";
 *
 * const store = new FileSystemStore("/path/to/events.zarr");
 * const ms = await MitchellStore.open(store);
 * ```
 *
 * @module
 */

export { FileSystemStore } from "@zarrita/storage";
