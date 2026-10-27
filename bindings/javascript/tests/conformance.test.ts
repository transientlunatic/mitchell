// @vitest-environment node
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { MitchellStore } from "../src/index.js";
import { FileSystemStore } from "../src/node.js";

const CONFORMANCE = join(
  dirname(fileURLToPath(import.meta.url)),
  "../../../tests/conformance",
);
const expected = JSON.parse(
  readFileSync(join(CONFORMANCE, "expected.json"), "utf8"),
);

interface Summary {
  shape: number[];
  head: number[];
  sum: number;
}

function check(data: ArrayLike<number>, shape: number[] | undefined, exp: Summary) {
  expect(shape).toEqual(exp.shape);
  exp.head.forEach((v, i) => expect(data[i]).toBeCloseTo(v, 12));
  let sum = 0;
  for (let i = 0; i < data.length; i++) sum += data[i];
  expect(Math.abs(sum - exp.sum)).toBeLessThanOrEqual(1e-9 * Math.max(1, Math.abs(exp.sum)));
}

const open = () =>
  MitchellStore.open(new FileSystemStore(join(CONFORMANCE, "store.zarr")));

describe("conformance fixture", () => {
  it("lists events and schema version", async () => {
    const ms = await open();
    expect(ms.schemaVersion).toBe(expected.schema_version);
    expect([...ms.eventNames()].sort()).toEqual(Object.keys(expected.events).sort());
  });

  for (const [eventName, analyses] of Object.entries<any>(expected.events)) {
    describe(eventName, () => {
      it("lists analyses", async () => {
        const event = await (await open()).get(eventName);
        expect([...event.analysisNames()].sort()).toEqual(Object.keys(analyses).sort());
      });

      for (const [analysisName, exp] of Object.entries<any>(analyses)) {
        it(`reads ${analysisName}`, async () => {
          const a = await (await (await open()).get(eventName)).get(analysisName);

          expect(a.attrs).toEqual(exp.attrs);
          expect(a.posterior!.parameterNames().sort()).toEqual(
            Object.keys(exp.posterior).sort(),
          );
          for (const [p, e] of Object.entries<Summary>(exp.posterior)) {
            const data = await a.posterior!.get(p);
            check(data, [data.length], e);
          }

          expect(a.priors!.analytic).toEqual(exp.prior_analytic);
          for (const [p, e] of Object.entries<Summary>(exp.prior_samples)) {
            const data = await a.priors!.samples!.get(p);
            check(data, [data.length], e);
          }

          for (const [det, e] of Object.entries<Summary>(exp.psds)) {
            const { data, shape } = await a.psds!.get(det);
            check(data, shape, e);
          }
          for (const [det, e] of Object.entries<Summary>(exp.calibration_envelope)) {
            const { data, shape } = await a.calibrationEnvelope!.get(det);
            check(data, shape, e);
          }

          expect(a.skymap!.metadata).toEqual(exp.skymap.attrs);
          const sky = await a.skymap!.getData();
          check(sky, [sky.length], exp.skymap.data);

          expect(a.config).toEqual(exp.config);
        });
      }
    });
  }

  it("rejects a store without a schema version", async () => {
    const empty = new Map<string, Uint8Array>([
      [
        "/zarr.json",
        new TextEncoder().encode(
          JSON.stringify({ zarr_format: 3, node_type: "group", attributes: {} }),
        ),
      ],
    ]);
    await expect(MitchellStore.open(empty as any)).rejects.toThrow(/mitchell_schema_version/);
  });
});
