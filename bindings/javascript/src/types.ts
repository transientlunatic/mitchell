/**
 * TypeScript types for the Mitchell zarr v3 schema.
 *
 * These interfaces mirror the Python Mitchell schema and are used
 * internally to parse consolidated metadata from the root zarr.json.
 */

/**
 * Metadata attributes stored on a gravitational-wave analysis group.
 *
 * These are promoted from the bilby HDF5 meta_data block when converting
 * a GWTC file to Mitchell format.  All fields are optional because not
 * every analysis will carry every attribute.
 */
export interface AnalysisAttrs {
  /** Waveform approximant, e.g. "IMRPhenomXPHM". */
  approximant?: string;
  cosmology?: string;
  delta_f?: number;
  distance_marginalization?: boolean;
  duration?: number;
  f_final?: number;
  /** Lower frequency cutoff in Hz. */
  f_low?: number;
  f_ref?: number;
  phase_marginalization?: boolean;
  reference_frame?: string;
  sampling_frequency?: number;
  start_time?: number;
  time_marginalization?: boolean;
  time_reference?: string;
  version?: string;
  description?: string;
  [key: string]: unknown;
}

/**
 * A single entry in the zarr v3 consolidated metadata map.
 *
 * The ``consolidated_metadata.metadata`` object inside the root
 * ``zarr.json`` maps relative paths to these records.  Groups carry
 * only ``attributes``; arrays additionally carry ``shape`` and
 * ``data_type``.
 */
export interface ConsolidatedEntry {
  zarr_format: 3;
  node_type: "group" | "array";
  attributes: Record<string, unknown>;
  /** Present for array nodes. */
  shape?: number[];
  /** Present for array nodes, e.g. ``"float64"``. */
  data_type?: string;
}

/**
 * A flat chunk of array data as returned by ``zarrita.get()``.
 *
 * The ``data`` buffer is a row-major (C-order) flattened typed array.
 */
export interface ArrayChunk {
  data: Float64Array;
  shape: number[];
  stride: number[];
}

/** Names and shapes of one analysis's data products, as listed in the index. */
export interface AnalysisIndexEntry {
  /** The analysis group's attributes. */
  attrs: AnalysisAttrs;
  /** Posterior parameter names. */
  posterior: string[];
  /** Number of posterior samples, when there is a posterior. */
  n_samples?: number;
  priors?: {
    /** Names of the sampled prior parameters. */
    samples: string[];
    /** Parameter name -> prior description string. */
    analytic: Record<string, string>;
  };
  /** Detector name -> array shape. */
  psds: Record<string, number[]>;
  /** Detector name -> array shape. */
  calibration_envelope: Record<string, number[]>;
  skymap?: { attrs: Record<string, unknown>; shape: number[] };
  /** Whether a ``config_file`` group exists (its contents are loaded lazily). */
  config_file?: boolean;
}

/** event name -> analysis name -> entry. */
export type Catalog = Record<string, Record<string, AnalysisIndexEntry>>;

/** The ``mitchell_index`` attribute on the store root (schema >= 0.2.0). */
export interface MitchellIndex {
  events: Catalog;
}
