/**
 * Core Mitchell API: {@link MitchellStore}, {@link Event}, and {@link Analysis}.
 *
 * The three classes mirror the Python ``mitchell`` package.  All
 * discovery (listing events, analyses, parameter names) is performed
 * synchronously from the consolidated metadata embedded in the root
 * ``zarr.json``; only actual array data loads are asynchronous.
 *
 * @example
 * ```typescript
 * import { MitchellStore } from "@mitchell/javascript";
 * import { FileSystemStore } from "@mitchell/javascript/node";
 *
 * const ms = await MitchellStore.open(new FileSystemStore("events.zarr"));
 * for await (const event of ms.events()) {
 *   for await (const analysis of event.analyses()) {
 *     const mass1 = await analysis.posterior!.get("mass_1");
 *   }
 * }
 * ```
 *
 * @module
 */

import * as zarrita from "zarrita";
import type { Readable } from "@zarrita/storage";
import type {
  AnalysisAttrs,
  ConsolidatedEntry,
  MitchellRootMetadata,
} from "./types.js";

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

const decoder = new TextDecoder();

/** Read the root zarr.json and return the parsed object. */
async function readRootJson(store: Readable): Promise<MitchellRootMetadata> {
  const bytes = await store.get("/zarr.json");
  if (!bytes) {
    throw new Error("Not a valid zarr store: /zarr.json not found");
  }
  return JSON.parse(decoder.decode(bytes)) as MitchellRootMetadata;
}

/**
 * Return names of all direct children of ``parentPath`` in the
 * consolidated metadata, optionally filtered by node type.
 *
 * @param consolidated  The ``consolidated_metadata.metadata`` map.
 * @param parentPath    Relative path (no leading ``/``).
 *                      Pass an empty string to list top-level entries.
 * @param nodeType      Optional filter: ``"array"`` or ``"group"``.
 */
function childNames(
  consolidated: Record<string, ConsolidatedEntry>,
  parentPath: string,
  nodeType?: "array" | "group",
): string[] {
  const prefix = parentPath ? `${parentPath}/` : "";
  const depth = parentPath ? parentPath.split("/").length + 1 : 1;
  return Object.keys(consolidated)
    .filter(
      (p) =>
        p.startsWith(prefix) &&
        p.split("/").length === depth &&
        (nodeType === undefined || consolidated[p].node_type === nodeType),
    )
    .map((p) => p.split("/").at(-1)!);
}

// ---------------------------------------------------------------------------
// PosteriorSamples / PriorSamples
// ---------------------------------------------------------------------------

/**
 * Columnar posterior sample arrays for one analysis.
 *
 * Parameter names are available synchronously from the consolidated
 * metadata; the underlying float64 data is loaded lazily on demand.
 */
export class PosteriorSamples {
  /** @internal */
  constructor(
    private readonly rootLoc: zarrita.Location<Readable>,
    private readonly basePath: string,
    private readonly params: readonly string[],
  ) {}

  /** Names of all available posterior parameters. */
  parameterNames(): string[] {
    return [...this.params];
  }

  /**
   * Load the float64 data for a single parameter.
   *
   * @param param  Parameter name, e.g. ``"mass_1"``.
   * @throws If ``param`` is not in {@link parameterNames}.
   */
  async get(param: string): Promise<Float64Array> {
    if (!this.params.includes(param)) {
      throw new Error(`Parameter not found: ${param}`);
    }
    const arr = await zarrita.open(
      this.rootLoc.resolve(`${this.basePath}/${param}`),
      { kind: "array" },
    );
    const chunk = await zarrita.get(arr, null);
    // All Mitchell posterior arrays are float64 by schema convention.
    return chunk.data as Float64Array;
  }

  /**
   * Load all parameters into memory in parallel.
   *
   * @returns A mapping of parameter name → {@link Float64Array}.
   */
  async getAll(): Promise<Record<string, Float64Array>> {
    const entries = await Promise.all(
      this.params.map(async (p) => [p, await this.get(p)] as const),
    );
    return Object.fromEntries(entries);
  }
}

// ---------------------------------------------------------------------------
// Priors
// ---------------------------------------------------------------------------

/**
 * Prior information for one analysis: both sampled and analytic forms.
 */
export class Priors {
  /** @internal */
  constructor(
    private readonly rootLoc: zarrita.Location<Readable>,
    private readonly priorsPath: string,
    private readonly priorParamNames: readonly string[],
    /** Mapping of parameter name → prior description string. */
    readonly analytic: Readonly<Record<string, string>>,
  ) {}

  /** Whether the store contains sampled prior draws. */
  hasSamples(): boolean {
    return this.priorParamNames.length > 0;
  }

  /**
   * Sampled prior draws, or ``null`` if none were stored.
   *
   * The returned object exposes the same API as {@link PosteriorSamples}.
   */
  get samples(): PosteriorSamples | null {
    if (!this.hasSamples()) return null;
    return new PosteriorSamples(
      this.rootLoc,
      `${this.priorsPath}/samples`,
      this.priorParamNames,
    );
  }
}

// ---------------------------------------------------------------------------
// PSDs / CalibrationEnvelope
// ---------------------------------------------------------------------------

/** A 2-D float64 array with its shape metadata. */
export interface Array2D {
  /** Row-major (C-order) flattened data. */
  data: Float64Array;
  /** ``[rows, cols]``. */
  shape: [number, number];
}

/**
 * Power Spectral Density arrays for one analysis, keyed by detector name.
 *
 * Each PSD is a ``(N, 2)`` float64 array where the columns are
 * ``[frequency_Hz, ASD]``.
 */
export class PSDs {
  /** @internal */
  constructor(
    private readonly rootLoc: zarrita.Location<Readable>,
    private readonly psdsPath: string,
    private readonly detectors: readonly string[],
    private readonly consolidated: Record<string, ConsolidatedEntry>,
  ) {}

  /** Names of all detectors that have a PSD stored. */
  detectorNames(): string[] {
    return [...this.detectors];
  }

  /**
   * Load the PSD array for a detector.
   *
   * @param detector  Detector name, e.g. ``"H1"`` or ``"L1"``.
   * @throws If ``detector`` is not in {@link detectorNames}.
   */
  async get(detector: string): Promise<Array2D> {
    if (!this.detectors.includes(detector)) {
      throw new Error(`Detector not found: ${detector}`);
    }
    const arr = await zarrita.open(
      this.rootLoc.resolve(`${this.psdsPath}/${detector}`),
      { kind: "array" },
    );
    const chunk = await zarrita.get(arr, null);
    const shape = this.consolidated[`${this.psdsPath}/${detector}`].shape!;
    return { data: chunk.data as Float64Array, shape: shape as [number, number] };
  }
}

/**
 * Calibration envelope arrays for one analysis, keyed by detector name.
 *
 * Each envelope is a ``(300, 7)`` float64 array.
 */
export class CalibrationEnvelope {
  /** @internal */
  constructor(
    private readonly rootLoc: zarrita.Location<Readable>,
    private readonly calPath: string,
    private readonly detectors: readonly string[],
    private readonly consolidated: Record<string, ConsolidatedEntry>,
  ) {}

  /** Names of all detectors with a calibration envelope stored. */
  detectorNames(): string[] {
    return [...this.detectors];
  }

  /**
   * Load the calibration envelope array for a detector.
   *
   * @param detector  Detector name, e.g. ``"H1"``.
   * @throws If ``detector`` is not in {@link detectorNames}.
   */
  async get(detector: string): Promise<Array2D> {
    if (!this.detectors.includes(detector)) {
      throw new Error(`Detector not found: ${detector}`);
    }
    const arr = await zarrita.open(
      this.rootLoc.resolve(`${this.calPath}/${detector}`),
      { kind: "array" },
    );
    const chunk = await zarrita.get(arr, null);
    const shape = this.consolidated[`${this.calPath}/${detector}`].shape!;
    return { data: chunk.data as Float64Array, shape: shape as [number, number] };
  }
}

// ---------------------------------------------------------------------------
// Skymap
// ---------------------------------------------------------------------------

/**
 * HEALPix skymap for one analysis.
 */
export class Skymap {
  /** @internal */
  constructor(
    private readonly rootLoc: zarrita.Location<Readable>,
    private readonly skymapPath: string,
    /** Raw zarr attributes for the skymap group (HEALPix metadata). */
    readonly metadata: Record<string, unknown>,
  ) {}

  /** Load the HEALPix pixel data as a flat float64 array. */
  async getData(): Promise<Float64Array> {
    const arr = await zarrita.open(
      this.rootLoc.resolve(`${this.skymapPath}/data`),
      { kind: "array" },
    );
    const chunk = await zarrita.get(arr, null);
    return chunk.data as Float64Array;
  }
}

// ---------------------------------------------------------------------------
// Analysis
// ---------------------------------------------------------------------------

/**
 * A single parameter-estimation analysis (one waveform approximant run)
 * within an event.
 *
 * All data-product accessors (``posterior``, ``psds``, …) are synchronous
 * and return ``null`` when a product was not stored for this analysis.
 * Actual array data is loaded asynchronously via the returned objects.
 */
export class Analysis {
  /** @internal */
  constructor(
    /** Analysis name, e.g. ``"IMRPhenomXPHM"``. */
    readonly name: string,
    /**
     * Analysis metadata attributes from the zarr group.
     *
     * Includes waveform approximant, frequency settings, and other
     * bilby meta_data fields promoted at import time.
     */
    readonly attrs: AnalysisAttrs,
    /** Posterior sample arrays, or ``null`` if not stored. */
    readonly posterior: PosteriorSamples | null,
    /** Prior information, or ``null`` if not stored. */
    readonly priors: Priors | null,
    /** PSD arrays, or ``null`` if not stored. */
    readonly psds: PSDs | null,
    /** Calibration envelope arrays, or ``null`` if not stored. */
    readonly calibrationEnvelope: CalibrationEnvelope | null,
    /** HEALPix skymap, or ``null`` if not stored. */
    readonly skymap: Skymap | null,
    /** Config file key-value pairs as a plain object. */
    readonly config: Record<string, unknown>,
  ) {}

  toString(): string {
    return `Analysis("${this.name}")`;
  }
}

// ---------------------------------------------------------------------------
// Analysis factory
// ---------------------------------------------------------------------------

/** Build an Analysis purely from consolidated metadata (no zarr I/O). */
function buildAnalysis(
  rootLoc: zarrita.Location<Readable>,
  consolidated: Record<string, ConsolidatedEntry>,
  analysisPath: string,
): Analysis {
  const name = analysisPath.split("/").at(-1)!;
  const attrs = (consolidated[analysisPath]?.attributes ?? {}) as AnalysisAttrs;

  // Posterior samples
  const postSamplesPath = `${analysisPath}/posterior/samples`;
  const postParams = childNames(consolidated, postSamplesPath, "array");
  const posterior =
    postParams.length > 0
      ? new PosteriorSamples(rootLoc, postSamplesPath, postParams)
      : null;

  // Prior samples + analytic priors
  const priorsPath = `${analysisPath}/priors`;
  let priors: Priors | null = null;
  if (priorsPath in consolidated) {
    const priorSamplesPath = `${priorsPath}/samples`;
    const priorParams = childNames(consolidated, priorSamplesPath, "array");
    const analyticPath = `${priorsPath}/analytic`;
    const analyticAttrs =
      analyticPath in consolidated
        ? (consolidated[analyticPath].attributes as Record<string, string>)
        : {};
    priors = new Priors(rootLoc, priorsPath, priorParams, analyticAttrs);
  }

  // PSDs
  const psdsPath = `${analysisPath}/psds`;
  const psdDetectors = childNames(consolidated, psdsPath, "array");
  const psds =
    psdDetectors.length > 0
      ? new PSDs(rootLoc, psdsPath, psdDetectors, consolidated)
      : null;

  // Calibration envelope
  const calPath = `${analysisPath}/calibration_envelope`;
  const calDetectors = childNames(consolidated, calPath, "array");
  const calibrationEnvelope =
    calDetectors.length > 0
      ? new CalibrationEnvelope(rootLoc, calPath, calDetectors, consolidated)
      : null;

  // Skymap
  const skymapPath = `${analysisPath}/skymap`;
  const skymapDataPath = `${skymapPath}/data`;
  const skymap =
    skymapDataPath in consolidated
      ? new Skymap(
          rootLoc,
          skymapPath,
          consolidated[skymapPath]?.attributes ?? {},
        )
      : null;

  // Config file
  const configPath = `${analysisPath}/config_file`;
  const config =
    configPath in consolidated ? consolidated[configPath].attributes : {};

  return new Analysis(
    name,
    attrs,
    posterior,
    priors,
    psds,
    calibrationEnvelope,
    skymap,
    config,
  );
}

// ---------------------------------------------------------------------------
// Event
// ---------------------------------------------------------------------------

/**
 * A gravitational-wave event containing one or more analyses.
 */
export class Event {
  /** @internal */
  constructor(
    private readonly rootLoc: zarrita.Location<Readable>,
    private readonly consolidated: Record<string, ConsolidatedEntry>,
    /** Event name, e.g. ``"GW150914_095045"``. */
    readonly name: string,
  ) {}

  /** Names of all analyses stored for this event. */
  analysisNames(): string[] {
    return childNames(this.consolidated, `events/${this.name}`);
  }

  /** Total number of analyses stored for this event. */
  size(): number {
    return this.analysisNames().length;
  }

  /**
   * Retrieve an analysis by name.
   *
   * @param analysisName  e.g. ``"IMRPhenomXPHM"``.
   * @throws If the analysis is not found.
   */
  async get(analysisName: string): Promise<Analysis> {
    const path = `events/${this.name}/${analysisName}`;
    if (!(path in this.consolidated)) {
      throw new Error(`Analysis not found: ${analysisName}`);
    }
    return buildAnalysis(this.rootLoc, this.consolidated, path);
  }

  /** Async-iterate over all analyses for this event. */
  async *analyses(): AsyncGenerator<Analysis> {
    for (const name of this.analysisNames()) {
      yield buildAnalysis(
        this.rootLoc,
        this.consolidated,
        `events/${this.name}/${name}`,
      );
    }
  }

  toString(): string {
    return `Event("${this.name}", analyses=[${this.analysisNames().join(", ")}])`;
  }
}

// ---------------------------------------------------------------------------
// MitchellStore
// ---------------------------------------------------------------------------

/**
 * A zarr-backed store of gravitational-wave analysis data products.
 *
 * Open an existing store with {@link MitchellStore.open}, passing any
 * zarrita-compatible store object.  For local filesystem access from
 * Node.js use {@link FileSystemStore} from ``@mitchell/javascript/node``;
 * for HTTP/cloud access use zarrita's built-in ``FetchStore``.
 *
 * Discovery (listing events and analyses) is performed synchronously
 * using consolidated metadata loaded at open time.
 *
 * @example Open a local store (Node.js)
 * ```typescript
 * import { FileSystemStore } from "@mitchell/javascript/node";
 * import { MitchellStore } from "@mitchell/javascript";
 *
 * const ms = await MitchellStore.open(new FileSystemStore("events.zarr"));
 * console.log(ms.eventNames()); // ["GW150914_095045", ...]
 * ```
 *
 * @example Open a remote store (browser)
 * ```typescript
 * import * as zarrita from "zarrita";
 * import { MitchellStore } from "@mitchell/javascript";
 *
 * const ms = await MitchellStore.open(
 *   new zarrita.FetchStore("https://my-bucket.s3.amazonaws.com/events.zarr")
 * );
 * ```
 */
export class MitchellStore {
  /** The Mitchell schema version of this store. */
  readonly schemaVersion: string;

  private constructor(
    private readonly rootLoc: zarrita.Location<Readable>,
    private readonly consolidated: Record<string, ConsolidatedEntry>,
    schemaVersion: string,
  ) {
    this.schemaVersion = schemaVersion;
  }

  /**
   * Open a Mitchell store from any zarrita-compatible store object.
   *
   * Reads and parses the root ``zarr.json`` (including consolidated
   * metadata) in a single request.
   *
   * @param store  Any {@link Readable} store.  Accepts
   *               {@link FileSystemStore} (Node.js), ``zarrita.FetchStore``
   *               (browser/HTTP), or an in-memory
   *               ``Map<string, Uint8Array>``.
   * @throws If ``/zarr.json`` is absent, the node is not a zarr v3 group,
   *         or ``mitchell_schema_version`` is missing from root attributes.
   */
  static async open(store: Readable): Promise<MitchellStore> {
    const rootMeta = await readRootJson(store);

    if (rootMeta.zarr_format !== 3 || rootMeta.node_type !== "group") {
      throw new Error(
        "Not a valid zarr v3 group at the store root",
      );
    }

    const version = rootMeta.attributes?.mitchell_schema_version;
    if (!version) {
      throw new Error(
        "Not a Mitchell store: mitchell_schema_version attribute not found in root",
      );
    }

    const consolidated = rootMeta.consolidated_metadata?.metadata ?? {};
    const rootLoc = zarrita.root(store);
    return new MitchellStore(rootLoc, consolidated, version);
  }

  /** Names of all events in the store (from consolidated metadata). */
  eventNames(): string[] {
    return childNames(this.consolidated, "events");
  }

  /** Total number of events in the store. */
  size(): number {
    return this.eventNames().length;
  }

  /**
   * Retrieve an event by name.
   *
   * @param eventName  e.g. ``"GW150914_095045"``.
   * @throws If the event is not found.
   */
  async get(eventName: string): Promise<Event> {
    if (!this.eventNames().includes(eventName)) {
      throw new Error(`Event not found: ${eventName}`);
    }
    return new Event(this.rootLoc, this.consolidated, eventName);
  }

  /** Async-iterate over all events in the store. */
  async *events(): AsyncGenerator<Event> {
    for (const name of this.eventNames()) {
      yield new Event(this.rootLoc, this.consolidated, name);
    }
  }

  toString(): string {
    const n = this.size();
    return `MitchellStore(${n} event${n !== 1 ? "s" : ""})`;
  }
}
