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
 * The ``consolidated_metadata`` block embedded in the root zarr.json.
 *
 * Python zarr v3 writes this block when
 * ``zarr.consolidate_metadata(store)`` is called.  The ``metadata``
 * map keys are relative paths with no leading ``/``.
 */
export interface ZarrV3ConsolidatedMetadata {
  kind: string;
  must_understand: boolean;
  metadata: Record<string, ConsolidatedEntry>;
}

/**
 * The root ``zarr.json`` content for a Mitchell store.
 */
export interface MitchellRootMetadata {
  zarr_format: 3;
  node_type: "group";
  attributes: {
    mitchell_schema_version: string;
    [key: string]: unknown;
  };
  consolidated_metadata?: ZarrV3ConsolidatedMetadata;
}

/**
 * A flat chunk of array data as returned by ``zarrita.get()``.
 *
 * The ``data`` buffer is a row-major (C-order) flattened typed array.
 * For float64 arrays this is a ``Float64Array``; use ``shape`` to
 * interpret the dimensionality.
 */
export interface ArrayChunk {
  data: Float64Array;
  shape: number[];
  stride: number[];
}
