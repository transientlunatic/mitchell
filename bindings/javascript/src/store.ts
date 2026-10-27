/**
 * Core Mitchell API: {@link MitchellStore}, {@link Event}, and {@link Analysis}.
 *
 * The classes mirror the Python ``mitchell`` package.  All discovery
 * (listing events, analyses, parameter names) is performed synchronously
 * from the ``mitchell_index`` attribute of the root ``zarr.json`` (or, for
 * schema 0.1.0 stores, its consolidated metadata); only actual array data
 * loads are asynchronous.
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
  AnalysisIndexEntry,
  Catalog,
  ConsolidatedEntry,
  MitchellIndex,
} from "./types.js";

type Consolidated = Record<string, ConsolidatedEntry>;
type RootLocation = zarrita.Location<Readable>;

/** Schema versions (major.minor) this reader understands. */
const SUPPORTED_SCHEMA_VERSIONS = ["0.1", "0.2"];

const decoder = new TextDecoder();

async function readRootJson(store: Readable): Promise<{
  zarr_format?: number;
  node_type?: string;
  attributes?: Record<string, unknown>;
  consolidated_metadata?: { metadata?: Consolidated };
}> {
  const bytes = await store.get("/zarr.json");
  if (!bytes) {
    throw new Error("Not a valid zarr store: /zarr.json not found");
  }
  return JSON.parse(decoder.decode(bytes));
}

/** Names of the direct children of ``parentPath`` (``""`` = root). */
function childNames(
  consolidated: Consolidated,
  parentPath: string,
  nodeType?: "group" | "array",
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

/** Load an entire array into memory. */
async function readArray(
  rootLoc: RootLocation,
  path: string,
): Promise<{ data: Float64Array; shape: number[] }> {
  // v3 only: plain `zarrita.open` also probes for v2 metadata (.zarray,
  // .zattrs), which wastes requests and fails outright on hosts that answer
  // HTML (200) for missing paths.
  const arr = await zarrita.open.v3(rootLoc.resolve(path), { kind: "array" });
  const chunk = await zarrita.get(arr, null);
  return { data: chunk.data as Float64Array, shape: chunk.shape };
}

/**
 * Build a {@link Catalog} from the consolidated metadata of a schema 0.1.0
 * store, which has no ``mitchell_index``.
 */
function catalogFromConsolidated(consolidated: Consolidated): Catalog {
  const catalog: Catalog = {};
  const arrayShapes = (path: string): Record<string, number[]> =>
    Object.fromEntries(
      childNames(consolidated, path, "array")
        .sort()
        .map((n) => [n, consolidated[`${path}/${n}`].shape ?? []]),
    );

  for (const event of childNames(consolidated, "events", "group").sort()) {
    catalog[event] = {};
    const eventPath = `events/${event}`;
    for (const name of childNames(consolidated, eventPath, "group").sort()) {
      const path = `${eventPath}/${name}`;
      const postShapes = arrayShapes(`${path}/posterior/samples`);
      const entry: AnalysisIndexEntry = {
        attrs: (consolidated[path].attributes ?? {}) as AnalysisAttrs,
        posterior: Object.keys(postShapes),
        psds: arrayShapes(`${path}/psds`),
        calibration_envelope: arrayShapes(`${path}/calibration_envelope`),
      };
      const first = Object.values(postShapes)[0];
      if (first) entry.n_samples = first[0];

      if (`${path}/priors` in consolidated) {
        entry.priors = {
          samples: Object.keys(arrayShapes(`${path}/priors/samples`)),
          analytic: (consolidated[`${path}/priors/analytic`]?.attributes ??
            {}) as Record<string, string>,
        };
      }
      if (`${path}/skymap/data` in consolidated) {
        entry.skymap = {
          attrs: consolidated[`${path}/skymap`]?.attributes ?? {},
          shape: consolidated[`${path}/skymap/data`].shape ?? [],
        };
      }
      if (`${path}/config_file` in consolidated) entry.config_file = true;
      catalog[event][name] = entry;
    }
  }
  return catalog;
}

// ---------------------------------------------------------------------------
// Data products
// ---------------------------------------------------------------------------

/**
 * Columnar posterior sample arrays for one analysis.
 *
 * Parameter names are available synchronously from the store index; the underlying float64 data is loaded lazily on demand.
 */
export class PosteriorSamples {
  /** @internal */
  constructor(
    private readonly rootLoc: RootLocation,
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
    return (await readArray(this.rootLoc, `${this.basePath}/${param}`)).data;
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

/**
 * Prior information for one analysis: both sampled and analytic forms.
 */
export class Priors {
  /** @internal */
  constructor(
    private readonly rootLoc: RootLocation,
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

/** A 2-D float64 array with its shape metadata. */
export interface Array2D {
  /** Row-major (C-order) flattened data. */
  data: Float64Array;
  /** ``[rows, cols]``. */
  shape: [number, number];
}

/** Shared implementation for per-detector 2-D arrays. */
class DetectorArrays {
  /** @internal */
  constructor(
    private readonly rootLoc: RootLocation,
    private readonly basePath: string,
    private readonly shapes: Readonly<Record<string, number[]>>,
  ) {}

  /** Names of all detectors that have an array stored. */
  detectorNames(): string[] {
    return Object.keys(this.shapes);
  }

  /**
   * Load the array for a detector.
   *
   * @param detector  Detector name, e.g. ``"H1"`` or ``"L1"``.
   * @throws If ``detector`` is not in {@link detectorNames}.
   */
  async get(detector: string): Promise<Array2D> {
    if (!(detector in this.shapes)) {
      throw new Error(`Detector not found: ${detector}`);
    }
    const { data } = await readArray(this.rootLoc, `${this.basePath}/${detector}`);
    return { data, shape: this.shapes[detector] as [number, number] };
  }
}

/**
 * Power Spectral Density arrays for one analysis, keyed by detector name.
 *
 * Each PSD is a ``(N, 2)`` float64 array where the columns are
 * ``[frequency_Hz, ASD]``.
 */
export class PSDs extends DetectorArrays {}

/**
 * Calibration envelope arrays for one analysis, keyed by detector name.
 *
 * Each envelope is a ``(300, 7)`` float64 array.
 */
export class CalibrationEnvelope extends DetectorArrays {}

/**
 * HEALPix skymap for one analysis.
 */
export class Skymap {
  /** @internal */
  constructor(
    private readonly rootLoc: RootLocation,
    private readonly skymapPath: string,
    /** Raw zarr attributes for the skymap group (HEALPix metadata). */
    readonly metadata: Record<string, unknown>,
  ) {}

  /** Load the HEALPix pixel data as a flat float64 array. */
  async getData(): Promise<Float64Array> {
    return (await readArray(this.rootLoc, `${this.skymapPath}/data`)).data;
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
    /** Analysis name, e.g. ``"C01:IMRPhenomXPHM"``. */
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
    /** Whether a config file is stored; see {@link getConfig}. */
    readonly hasConfig: boolean,
    private readonly loadConfig: () => Promise<Record<string, unknown>>,
  ) {}

  /**
   * The analysis's config file as a key-value object (``{}`` if none).
   *
   * Loaded on demand rather than listed in the store index, because config
   * files are comparatively large.
   */
  async getConfig(): Promise<Record<string, unknown>> {
    return this.hasConfig ? this.loadConfig() : {};
  }

  toString(): string {
    return `Analysis("${this.name}")`;
  }
}

function buildAnalysis(
  rootLoc: RootLocation,
  analysisPath: string,
  entry: AnalysisIndexEntry,
): Analysis {
  const name = analysisPath.split("/").at(-1)!;

  const postSamplesPath = `${analysisPath}/posterior/samples`;
  const posterior =
    entry.posterior.length > 0
      ? new PosteriorSamples(rootLoc, postSamplesPath, entry.posterior)
      : null;

  const priors = entry.priors
    ? new Priors(
        rootLoc,
        `${analysisPath}/priors`,
        entry.priors.samples,
        entry.priors.analytic,
      )
    : null;

  const detectors = (shapes: Record<string, number[]> | undefined) =>
    shapes && Object.keys(shapes).length > 0 ? shapes : null;
  const psdShapes = detectors(entry.psds);
  const psds = psdShapes
    ? new PSDs(rootLoc, `${analysisPath}/psds`, psdShapes)
    : null;
  const calShapes = detectors(entry.calibration_envelope);
  const calibrationEnvelope = calShapes
    ? new CalibrationEnvelope(
        rootLoc,
        `${analysisPath}/calibration_envelope`,
        calShapes,
      )
    : null;

  const skymap = entry.skymap
    ? new Skymap(rootLoc, `${analysisPath}/skymap`, entry.skymap.attrs)
    : null;

  const configPath = `${analysisPath}/config_file`;
  const loadConfig = async () => {
    const group = await zarrita.open.v3(rootLoc.resolve(configPath), {
      kind: "group",
    });
    return group.attrs as Record<string, unknown>;
  };

  return new Analysis(
    name,
    entry.attrs ?? {},
    posterior,
    priors,
    psds,
    calibrationEnvelope,
    skymap,
    entry.config_file === true,
    loadConfig,
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
    private readonly rootLoc: RootLocation,
    private readonly analysisEntries: Readonly<
      Record<string, AnalysisIndexEntry>
    >,
    /** Event name, e.g. ``"GW150914_095045"``. */
    readonly name: string,
  ) {}

  /** Names of all analyses stored for this event. */
  analysisNames(): string[] {
    return Object.keys(this.analysisEntries);
  }

  /** Total number of analyses stored for this event. */
  size(): number {
    return this.analysisNames().length;
  }

  /**
   * Retrieve an analysis by name.
   *
   * @param analysisName  e.g. ``"C01:IMRPhenomXPHM"``.
   * @throws If the analysis is not found.
   */
  async get(analysisName: string): Promise<Analysis> {
    const entry = this.analysisEntries[analysisName];
    if (!entry) {
      throw new Error(`Analysis not found: ${analysisName}`);
    }
    return buildAnalysis(
      this.rootLoc,
      `events/${this.name}/${analysisName}`,
      entry,
    );
  }

  /** Async-iterate over all analyses for this event. */
  async *analyses(): AsyncGenerator<Analysis> {
    for (const name of this.analysisNames()) {
      yield this.get(name);
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
 * Node.js use ``FileSystemStore`` from ``@mitchell/javascript/node``;
 * for HTTP/cloud access use zarrita's built-in ``FetchStore``.
 *
 * Discovery (listing events and analyses) is performed synchronously
 * using the index loaded at open time.
 */
export class MitchellStore {
  private constructor(
    private readonly rootLoc: RootLocation,
    private readonly catalog: Catalog,
    /** The Mitchell schema version of this store. */
    readonly schemaVersion: string,
  ) {}

  /**
   * Open a Mitchell store from any zarrita-compatible store object.
   *
   * Reads and parses the root ``zarr.json`` in a single request.  Its
   * ``mitchell_index`` attribute (schema 0.2) lists every event, analysis and
   * data product; stores written with schema 0.1 are listed from their
   * consolidated metadata instead.
   *
   * @param store  Any {@link Readable} store: ``FileSystemStore`` (Node.js),
   *               ``zarrita.FetchStore`` (browser/HTTP), or an in-memory
   *               ``Map<string, Uint8Array>``.
   * @throws If ``/zarr.json`` is absent, the node is not a zarr v3 group,
   *         ``mitchell_schema_version`` is missing or unsupported, or the
   *         root carries neither an index nor consolidated metadata.
   */
  static async open(store: Readable): Promise<MitchellStore> {
    const rootMeta = await readRootJson(store);

    if (rootMeta.zarr_format !== 3 || rootMeta.node_type !== "group") {
      throw new Error("Not a valid zarr v3 group at the store root");
    }

    const version = rootMeta.attributes?.mitchell_schema_version as
      | string
      | undefined;
    if (!version) {
      throw new Error(
        "Not a Mitchell store: mitchell_schema_version attribute not found in root",
      );
    }
    const majorMinor = version.split(".").slice(0, 2).join(".");
    if (!SUPPORTED_SCHEMA_VERSIONS.includes(majorMinor)) {
      throw new Error(
        `Unsupported Mitchell schema version ${version} ` +
          `(this reader supports ${SUPPORTED_SCHEMA_VERSIONS.join(", ")})`,
      );
    }

    const index = rootMeta.attributes?.mitchell_index as
      | MitchellIndex
      | undefined;
    const consolidated = rootMeta.consolidated_metadata?.metadata;
    let catalog: Catalog;
    if (index) {
      catalog = index.events ?? {};
    } else if (consolidated) {
      catalog = catalogFromConsolidated(consolidated);
    } else {
      throw new Error(
        "Cannot list the store: root zarr.json has neither a mitchell_index " +
          "attribute nor consolidated metadata (run `mitchell reindex`)",
      );
    }
    return new MitchellStore(zarrita.root(store), catalog, version);
  }

  /** Names of all events in the store. */
  eventNames(): string[] {
    return Object.keys(this.catalog);
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
    const analyses = this.catalog[eventName];
    if (!analyses) {
      throw new Error(`Event not found: ${eventName}`);
    }
    return new Event(this.rootLoc, analyses, eventName);
  }

  /** Async-iterate over all events in the store. */
  async *events(): AsyncGenerator<Event> {
    for (const name of this.eventNames()) {
      yield this.get(name);
    }
  }

  toString(): string {
    const n = this.size();
    return `MitchellStore(${n} event${n !== 1 ? "s" : ""})`;
  }
}
