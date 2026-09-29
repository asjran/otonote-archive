import { createHash } from "node:crypto";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";


function resolveStaticDataRoot() {
  const candidates = [
    path.resolve(process.cwd(), "src/data/anontokyo-player-guide"),
    path.resolve(process.cwd(), "site/src/data/anontokyo-player-guide"),
  ];
  for (const candidate of candidates) {
    if (existsSync(path.join(candidate, "manifest.json"))) {
      return candidate;
    }
  }
  return candidates[0];
}
const STATIC_DATA_ROOT = resolveStaticDataRoot();
const STATIC_MEDIA_MANIFEST = path.join(STATIC_DATA_ROOT, "anontokyo-media.json");

const REQUIRED_FILES = Object.freeze([
  "store.json",
  "growth.json",
  "goods.json",
  "customers.json",
  "wardrobe.json",
  "inspiration.json",
  "furniture.json",
  "themes.json",
  "stages.json",
  "chats.json",
  "tasks.json",
  "staff.json",
  "guide.json",
  "mechanics.json"
]);
const OPTIONAL_FILES = Object.freeze(["studio.json"]);
const PRIVATE_TERMS = Object.freeze([
  "MasterAT",
  "sourceTable",
  "sourceId",
  "sourceFields",
  "interpretationStatus",
  "warnings",
  "abilityId",
  "taskTypeId",
  "categoryId",
  "tagIds",
  "charactersByCanUse",
  "charactersByPath",
  "characterAttributionStatus",
  "frameType",
  "hintText",
  "carouselId",
  "speakerMapping",
  "clientSemanticsVerified",
  "charactersByPath"
]);


function fail(message) {
  throw new Error(`AnonTokyo private preview: ${message}`);
}


function readGuideFile(root, name) {
  let bytes;
  try {
    bytes = readFileSync(path.join(root, name));
  } catch {
    fail(`required player guide file is unreadable: ${name}`);
  }
  const text = bytes.toString("utf8");
  if (PRIVATE_TERMS.some((term) => text.includes(term))) {
    fail(`player guide contains a private term: ${name}`);
  }
  let value;
  try {
    value = JSON.parse(text);
  } catch {
    fail(`player guide JSON is invalid: ${name}`);
  }
  return { bytes, value };
}


function assertDocument(value, name, releaseId) {
  const expectedSchemaVersion = name === "studio.json" ? 2 : 1;
  const collection =
    name === "store.json"
      ? value?.levels
      : name === "guide.json"
      ? value?.chapters
      : name === "mechanics.json"
      ? value?.sections
      : name === "studio.json"
      ? value?.furniture
      : value?.records;
  if (
    !value ||
    value.schemaVersion !== expectedSchemaVersion ||
    value.sourceReleaseId !== releaseId ||
    !Array.isArray(collection)
  ) {
    fail(`player guide contract is invalid: ${name}`);
  }
}


export function loadPlayerGuide(root) {
  if (typeof root !== "string" || !root.trim()) {
    fail("OURNOTES_ANONTOKYO_PLAYER_GUIDE_ROOT is required");
  }
  const { value: manifest } = readGuideFile(root, "manifest.json");
  if (
    !manifest ||
    manifest.schemaVersion !== 1 ||
    typeof manifest.sourceReleaseId !== "string" ||
    !manifest.files ||
    typeof manifest.files !== "object" ||
    !manifest.formulaCapabilities ||
    typeof manifest.formulaCapabilities !== "object"
  ) {
    fail("player guide manifest contract is invalid");
  }
  const documents = {};
  for (const name of REQUIRED_FILES) {
    const expected = manifest.files[name];
    if (!expected || typeof expected.sha256 !== "string") {
      fail(`player guide manifest is missing file evidence: ${name}`);
    }
    const { bytes, value } = readGuideFile(root, name);
    const actual = createHash("sha256").update(bytes).digest("hex");
    if (actual !== expected.sha256) {
      fail(`player guide SHA-256 mismatch: ${name}`);
    }
    assertDocument(value, name, manifest.sourceReleaseId);
    documents[name.replace(".json", "")] = value;
  }
  for (const name of OPTIONAL_FILES) {
    const expected = manifest.files[name];
    if (!expected) continue;
    if (typeof expected.sha256 !== "string") {
      fail(`player guide manifest is missing file evidence: ${name}`);
    }
    const { bytes, value } = readGuideFile(root, name);
    const actual = createHash("sha256").update(bytes).digest("hex");
    if (actual !== expected.sha256) {
      fail(`player guide SHA-256 mismatch: ${name}`);
    }
    assertDocument(value, name, manifest.sourceReleaseId);
    documents[name.replace(".json", "")] = value;
  }
  return { manifest, ...documents };
}


function loadStagedMedia(manifestPath) {
  if (!manifestPath) return [];
  let value;
  try {
    value = JSON.parse(readFileSync(manifestPath, "utf8"));
  } catch {
    fail("staged media manifest is unreadable");
  }
  if (
    !Array.isArray(value) ||
    value.some((entry) =>
      !entry ||
      typeof entry.logicalKey !== "string" ||
      typeof entry.publicUrl !== "string" ||
      !entry.publicUrl.startsWith("/media/anontokyo/")
    )
  ) {
    fail("staged media manifest contract is invalid");
  }
  return value;
}

function resolveMediaManifestPath(environment) {
  if (environment.OURNOTES_ANONTOKYO_STAGED_MEDIA_MANIFEST) {
    return environment.OURNOTES_ANONTOKYO_STAGED_MEDIA_MANIFEST;
  }
  try {
    const stat = readFileSync(STATIC_MEDIA_MANIFEST, "utf8");
    if (stat) return STATIC_MEDIA_MANIFEST;
  } catch {
    // static manifest not available
  }
  return null;
}


function route(view, props) {
  return { params: { view }, props };
}


function detailRoutes(prefix, records, props) {
  return records.map((record) =>
    route(`${prefix}/${record.id}`, {
      ...props,
      page: "detail",
      section: prefix,
      record
    })
  );
}


export function privatePreviewPaths(environment = process.env) {
  const enabled = environment.PUBLIC_ANONTOKYO_ENABLED === "1"
    || environment.OURNOTES_ANONTOKYO_ENABLED === "1"
    || environment.OURNOTES_ANONTOKYO_PRIVATE_PREVIEW === "1";
  if (!enabled) return [];
  const dataRoot = environment.OURNOTES_ANONTOKYO_PLAYER_GUIDE_ROOT || STATIC_DATA_ROOT;
  const guide = loadPlayerGuide(dataRoot);
  const common = {
    manifest: guide.manifest,
    stagedMedia: loadStagedMedia(resolveMediaManifestPath(environment))
  };
  return [
    route(undefined, { ...common, page: "home" }),
    route("store", { ...common, page: "store", dataset: guide.store }),
    route("growth", { ...common, page: "growth", dataset: guide.growth }),
    route("goods", { ...common, page: "goods", dataset: guide.goods }),
    route("customers", { ...common, page: "customers", dataset: guide.customers }),
    route("wardrobe", { ...common, page: "wardrobe", dataset: guide.wardrobe }),
    route("inspiration", { ...common, page: "inspiration", dataset: guide.inspiration }),
    route("furniture", { ...common, page: "furniture", dataset: guide.furniture }),
    route("themes", { ...common, page: "themes", dataset: guide.themes }),
    route("stages", { ...common, page: "stages", dataset: guide.stages }),
    route("chats", { ...common, page: "chats", dataset: guide.chats }),
    route("tasks", { ...common, page: "tasks", dataset: guide.tasks }),
    route("staff", { ...common, page: "staff", dataset: guide.staff }),
    ...(guide.staff.assignmentStudio
      ? [route("staff-assignment", { ...common, page: "staff-assignment", dataset: guide.staff })]
      : []),
    ...(guide.studio
      ? [route("studio", { ...common, page: "studio", dataset: guide.studio, staffDataset: guide.staff })]
      : []),
    route("guide", { ...common, page: "guide", dataset: guide.guide }),
    route("mechanics", { ...common, page: "mechanics", dataset: guide.mechanics }),
    ...detailRoutes("goods", guide.goods.records, common),
    ...detailRoutes("furniture", guide.furniture.records, common),
    ...detailRoutes("themes", guide.themes.records, common),
    ...detailRoutes("stages", guide.stages.records, common),
    ...detailRoutes("chats", guide.chats.records, common),
    ...detailRoutes("tasks", guide.tasks.records, common),
    ...detailRoutes("staff", guide.staff.records, common),
    ...detailRoutes("wardrobe", guide.wardrobe.records, common)
  ];
}
