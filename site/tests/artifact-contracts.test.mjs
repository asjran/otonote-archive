import assert from "node:assert/strict";
import test from "node:test";

import { validateArtifact } from "../src/lib/artifact-contracts.ts";

test("validateArtifact returns an artifact that matches its runtime contract", () => {
  const artifact = {
    schemaVersion: 6,
    release: { id: "release-jp" },
    bands: [{ id: "band-1" }]
  };

  const validated = validateArtifact("catalog.json", artifact, {
    schemaVersion: 6,
    fields: {
      release: "object",
      "release.id": "string",
      bands: "array",
      "bands[]": "object",
      "bands[].id": "string"
    }
  });

  assert.equal(validated, artifact);
});

test("validateArtifact reports the artifact and schemaVersion on version drift", () => {
  assert.throws(
    () =>
      validateArtifact("release-index.json", { schemaVersion: 2 }, {
        schemaVersion: 1,
        fields: {}
      }),
    /release-index\.json: schemaVersion must be 1/
  );
});

test("validateArtifact reports the artifact and nested field on shape drift", () => {
  assert.throws(
    () =>
      validateArtifact("catalog.json", {
        schemaVersion: 6,
        bands: [{ id: 42 }]
      }, {
        schemaVersion: 6,
        fields: {
          bands: "array",
          "bands[]": "object",
          "bands[].id": "string"
        }
      }),
    /catalog\.json: bands\[\]\.id must be string/
  );
});

test("validateArtifact rejects a non-object root", () => {
  assert.throws(
    () =>
      validateArtifact("story-database.json", [], {
        schemaVersion: 1,
        fields: {}
      }),
    /story-database\.json: root must be an object/
  );
});
