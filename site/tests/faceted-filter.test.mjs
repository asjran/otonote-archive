import assert from "node:assert/strict";
import test from "node:test";

import {
  evaluateFacets,
  facetParams,
  selectedFacetsFromParams
} from "../src/lib/faceted-filter.mjs";

const records = [
  {
    id: "mygo-1",
    search: "高松燈 MyGO!!!!!",
    facets: {
      character: ["character-tomori"],
      band: ["band-mygo"],
      rarity: ["4"],
      attribute: ["1"]
    }
  },
  {
    id: "mygo-2",
    search: "千早愛音 MyGO!!!!!",
    facets: {
      character: ["character-anon"],
      band: ["band-mygo"],
      rarity: ["3"],
      attribute: ["2"]
    }
  },
  {
    id: "mujica-1",
    search: "三角初華 Ave Mujica",
    facets: {
      character: ["character-uika"],
      band: ["band-mujica"],
      rarity: ["4"],
      attribute: ["1"]
    }
  }
];

test("combines selections with OR inside a facet and AND across facets", () => {
  const result = evaluateFacets(records, {
    query: "",
    selected: {
      character: ["character-tomori", "character-anon"],
      rarity: ["4"]
    }
  });

  assert.deepEqual(result.records.map((record) => record.id), ["mygo-1"]);
});

test("reports contextual option counts and disables impossible combinations", () => {
  const result = evaluateFacets(records, {
    query: "",
    selected: { character: ["character-tomori"] }
  });

  assert.equal(result.counts.band["band-mygo"], 1);
  assert.equal(result.counts.band["band-mujica"], 0);
  assert.deepEqual(result.disabled.band, ["band-mujica"]);
});

test("round trips multi-select facets through stable URL ids", () => {
  const params = facetParams({
    query: "燈",
    selected: {
      character: ["character-tomori", "character-anon"],
      band: ["band-mygo"]
    },
    sort: "desc"
  });

  assert.equal(
    params.toString(),
    "q=%E7%87%88&character=character-tomori%2Ccharacter-anon&band=band-mygo&sort=desc"
  );
  assert.deepEqual(selectedFacetsFromParams(params, ["character", "band"]), {
    character: ["character-tomori", "character-anon"],
    band: ["band-mygo"]
  });
});
