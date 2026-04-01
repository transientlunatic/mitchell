import { describe, it, expect, beforeAll } from "vitest";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { MitchellStore } from "../src/store.js";
import { FileSystemStore } from "../src/node.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const FIXTURE_PATH = join(__dirname, "fixture");

const PARAMS = ["mass_1", "mass_2", "chi_eff", "luminosity_distance"];
const DETECTORS = ["H1", "L1"];
const N_SAMPLES = 50;
const N_PSD = 128;

// ---------------------------------------------------------------------------
// MitchellStore
// ---------------------------------------------------------------------------

describe("MitchellStore", () => {
  let ms: MitchellStore;

  beforeAll(async () => {
    ms = await MitchellStore.open(new FileSystemStore(FIXTURE_PATH));
  });

  it("reads the schema version", () => {
    expect(ms.schemaVersion).toBe("0.1.0");
  });

  it("returns the event names synchronously", () => {
    expect(ms.eventNames()).toEqual(["GW000000"]);
  });

  it("counts events", () => {
    expect(ms.size()).toBe(1);
  });

  it("iterates events", async () => {
    const events = [];
    for await (const event of ms.events()) {
      events.push(event);
    }
    expect(events).toHaveLength(1);
  });

  it("gets an event by name", async () => {
    const event = await ms.get("GW000000");
    expect(event.name).toBe("GW000000");
  });

  it("throws for a missing event", async () => {
    await expect(ms.get("DOESNOTEXIST")).rejects.toThrow(/not found/i);
  });

  it("rejects a store without mitchell_schema_version", async () => {
    // An empty Map is a valid in-memory zarr store but has no root zarr.json
    const emptyStore = new Map<string, Uint8Array>();
    await expect(MitchellStore.open(emptyStore)).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// Event
// ---------------------------------------------------------------------------

describe("Event", () => {
  it("has the correct name", async () => {
    const ms = await MitchellStore.open(new FileSystemStore(FIXTURE_PATH));
    const event = await ms.get("GW000000");
    expect(event.name).toBe("GW000000");
  });

  it("returns analysis names synchronously", async () => {
    const ms = await MitchellStore.open(new FileSystemStore(FIXTURE_PATH));
    const event = await ms.get("GW000000");
    expect(event.analysisNames()).toContain("IMRPhenomXPHM");
    expect(event.analysisNames()).toContain("NRSur7dq4");
  });

  it("counts analyses", async () => {
    const ms = await MitchellStore.open(new FileSystemStore(FIXTURE_PATH));
    const event = await ms.get("GW000000");
    expect(event.size()).toBe(2);
  });

  it("iterates analyses", async () => {
    const ms = await MitchellStore.open(new FileSystemStore(FIXTURE_PATH));
    const event = await ms.get("GW000000");
    const analyses = [];
    for await (const a of event.analyses()) {
      analyses.push(a);
    }
    expect(analyses).toHaveLength(2);
  });

  it("gets an analysis by name", async () => {
    const ms = await MitchellStore.open(new FileSystemStore(FIXTURE_PATH));
    const event = await ms.get("GW000000");
    const analysis = await event.get("IMRPhenomXPHM");
    expect(analysis.name).toBe("IMRPhenomXPHM");
  });

  it("throws for a missing analysis", async () => {
    const ms = await MitchellStore.open(new FileSystemStore(FIXTURE_PATH));
    const event = await ms.get("GW000000");
    await expect(event.get("DOESNOTEXIST")).rejects.toThrow(/not found/i);
  });
});

// ---------------------------------------------------------------------------
// Analysis — metadata
// ---------------------------------------------------------------------------

describe("Analysis.attrs", () => {
  it("has the approximant attribute", async () => {
    const ms = await MitchellStore.open(new FileSystemStore(FIXTURE_PATH));
    const analysis = await (await ms.get("GW000000")).get("IMRPhenomXPHM");
    expect(analysis.attrs.approximant).toBe("IMRPhenomXPHM");
  });

  it("has the f_low attribute", async () => {
    const ms = await MitchellStore.open(new FileSystemStore(FIXTURE_PATH));
    const analysis = await (await ms.get("GW000000")).get("IMRPhenomXPHM");
    expect(analysis.attrs.f_low).toBe(20.0);
  });
});

// ---------------------------------------------------------------------------
// Analysis — posterior
// ---------------------------------------------------------------------------

describe("Analysis.posterior", () => {
  it("is not null", async () => {
    const ms = await MitchellStore.open(new FileSystemStore(FIXTURE_PATH));
    const analysis = await (await ms.get("GW000000")).get("IMRPhenomXPHM");
    expect(analysis.posterior).not.toBeNull();
  });

  it("lists parameter names", async () => {
    const ms = await MitchellStore.open(new FileSystemStore(FIXTURE_PATH));
    const analysis = await (await ms.get("GW000000")).get("IMRPhenomXPHM");
    const params = analysis.posterior!.parameterNames();
    for (const p of PARAMS) {
      expect(params).toContain(p);
    }
  });

  it("loads a single parameter as Float64Array of correct length", async () => {
    const ms = await MitchellStore.open(new FileSystemStore(FIXTURE_PATH));
    const analysis = await (await ms.get("GW000000")).get("IMRPhenomXPHM");
    const mass1 = await analysis.posterior!.get("mass_1");
    expect(mass1).toBeInstanceOf(Float64Array);
    expect(mass1.length).toBe(N_SAMPLES);
  });

  it("throws for an unknown parameter", async () => {
    const ms = await MitchellStore.open(new FileSystemStore(FIXTURE_PATH));
    const analysis = await (await ms.get("GW000000")).get("IMRPhenomXPHM");
    await expect(analysis.posterior!.get("NOPE")).rejects.toThrow(/not found/i);
  });

  it("loads all parameters via getAll()", async () => {
    const ms = await MitchellStore.open(new FileSystemStore(FIXTURE_PATH));
    const analysis = await (await ms.get("GW000000")).get("IMRPhenomXPHM");
    const all = await analysis.posterior!.getAll();
    for (const p of PARAMS) {
      expect(all[p]).toBeInstanceOf(Float64Array);
      expect(all[p].length).toBe(N_SAMPLES);
    }
  });
});

// ---------------------------------------------------------------------------
// Analysis — priors
// ---------------------------------------------------------------------------

describe("Analysis.priors", () => {
  it("is not null", async () => {
    const ms = await MitchellStore.open(new FileSystemStore(FIXTURE_PATH));
    const analysis = await (await ms.get("GW000000")).get("IMRPhenomXPHM");
    expect(analysis.priors).not.toBeNull();
  });

  it("has analytic prior strings", async () => {
    const ms = await MitchellStore.open(new FileSystemStore(FIXTURE_PATH));
    const analysis = await (await ms.get("GW000000")).get("IMRPhenomXPHM");
    const analytic = analysis.priors!.analytic;
    expect(analytic["mass_1"]).toMatch(/Uniform/);
  });

  it("indicates prior samples are present", async () => {
    const ms = await MitchellStore.open(new FileSystemStore(FIXTURE_PATH));
    const analysis = await (await ms.get("GW000000")).get("IMRPhenomXPHM");
    expect(analysis.priors!.hasSamples()).toBe(true);
  });

  it("loads prior samples", async () => {
    const ms = await MitchellStore.open(new FileSystemStore(FIXTURE_PATH));
    const analysis = await (await ms.get("GW000000")).get("IMRPhenomXPHM");
    const samples = analysis.priors!.samples!;
    const mass1 = await samples.get("mass_1");
    expect(mass1).toBeInstanceOf(Float64Array);
    expect(mass1.length).toBe(N_SAMPLES);
  });
});

// ---------------------------------------------------------------------------
// Analysis — PSDs
// ---------------------------------------------------------------------------

describe("Analysis.psds", () => {
  it("is not null", async () => {
    const ms = await MitchellStore.open(new FileSystemStore(FIXTURE_PATH));
    const analysis = await (await ms.get("GW000000")).get("IMRPhenomXPHM");
    expect(analysis.psds).not.toBeNull();
  });

  it("lists detector names", async () => {
    const ms = await MitchellStore.open(new FileSystemStore(FIXTURE_PATH));
    const analysis = await (await ms.get("GW000000")).get("IMRPhenomXPHM");
    const detectors = analysis.psds!.detectorNames();
    for (const d of DETECTORS) {
      expect(detectors).toContain(d);
    }
  });

  it("loads a PSD with correct shape and data type", async () => {
    const ms = await MitchellStore.open(new FileSystemStore(FIXTURE_PATH));
    const analysis = await (await ms.get("GW000000")).get("IMRPhenomXPHM");
    const psd = await analysis.psds!.get("H1");
    expect(psd.shape).toEqual([N_PSD, 2]);
    expect(psd.data).toBeInstanceOf(Float64Array);
    expect(psd.data.length).toBe(N_PSD * 2);
  });
});

// ---------------------------------------------------------------------------
// Analysis — calibration envelope
// ---------------------------------------------------------------------------

describe("Analysis.calibrationEnvelope", () => {
  it("is not null", async () => {
    const ms = await MitchellStore.open(new FileSystemStore(FIXTURE_PATH));
    const analysis = await (await ms.get("GW000000")).get("IMRPhenomXPHM");
    expect(analysis.calibrationEnvelope).not.toBeNull();
  });

  it("loads calibration data with correct shape", async () => {
    const ms = await MitchellStore.open(new FileSystemStore(FIXTURE_PATH));
    const analysis = await (await ms.get("GW000000")).get("IMRPhenomXPHM");
    const cal = await analysis.calibrationEnvelope!.get("H1");
    expect(cal.shape).toEqual([300, 7]);
    expect(cal.data).toBeInstanceOf(Float64Array);
  });
});

// ---------------------------------------------------------------------------
// Analysis — skymap
// ---------------------------------------------------------------------------

describe("Analysis.skymap", () => {
  it("is null when not present in the store", async () => {
    const ms = await MitchellStore.open(new FileSystemStore(FIXTURE_PATH));
    const analysis = await (await ms.get("GW000000")).get("IMRPhenomXPHM");
    expect(analysis.skymap).toBeNull();
  });

  it("is not null when a skymap is stored", async () => {
    const ms = await MitchellStore.open(new FileSystemStore(FIXTURE_PATH));
    const analysis = await (await ms.get("GW000000")).get("NRSur7dq4");
    expect(analysis.skymap).not.toBeNull();
  });

  it("exposes skymap group metadata as attrs", async () => {
    const ms = await MitchellStore.open(new FileSystemStore(FIXTURE_PATH));
    const analysis = await (await ms.get("GW000000")).get("NRSur7dq4");
    expect(analysis.skymap!.metadata["nside"]).toBe(512);
  });

  it("loads skymap pixel data as Float64Array", async () => {
    const ms = await MitchellStore.open(new FileSystemStore(FIXTURE_PATH));
    const analysis = await (await ms.get("GW000000")).get("NRSur7dq4");
    const data = await analysis.skymap!.getData();
    expect(data).toBeInstanceOf(Float64Array);
    expect(data.length).toBe(192);
  });
});

// ---------------------------------------------------------------------------
// Analysis — config
// ---------------------------------------------------------------------------

describe("Analysis.config", () => {
  it("returns config key-value pairs", async () => {
    const ms = await MitchellStore.open(new FileSystemStore(FIXTURE_PATH));
    const analysis = await (await ms.get("GW000000")).get("IMRPhenomXPHM");
    expect(analysis.config["sampler"]).toBe("dynesty");
    expect(analysis.config["duration"]).toBe("4");
  });
});
