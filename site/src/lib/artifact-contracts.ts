type JsonObject = Record<string, unknown>;

type ArtifactFieldKind =
  | "array"
  | "boolean"
  | "number"
  | "object"
  | "string";

interface ArtifactContract<SchemaVersion extends number> {
  schemaVersion: SchemaVersion;
  fields: Readonly<Record<string, ArtifactFieldKind>>;
}

function isObject(value: unknown): value is JsonObject {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function valuesAtPath(root: unknown, path: string): unknown[] {
  let values = [root];
  for (const rawSegment of path.split(".")) {
    const each = rawSegment.endsWith("[]");
    const segment = each ? rawSegment.slice(0, -2) : rawSegment;
    const next: unknown[] = [];
    for (const value of values) {
      const child = isObject(value) ? value[segment] : undefined;
      if (each) {
        next.push(...(Array.isArray(child) ? child : [undefined]));
      } else {
        next.push(child);
      }
    }
    values = next;
  }
  return values;
}

function matchesKind(value: unknown, kind: ArtifactFieldKind): boolean {
  if (kind === "array") return Array.isArray(value);
  if (kind === "object") return isObject(value);
  return typeof value === kind;
}

export function validateArtifact<T extends { schemaVersion: number }>(
  artifactName: string,
  value: unknown,
  contract: ArtifactContract<T["schemaVersion"]>
): T {
  if (!isObject(value)) {
    throw new TypeError(`${artifactName}: root must be an object`);
  }
  if (value.schemaVersion !== contract.schemaVersion) {
    throw new TypeError(
      `${artifactName}: schemaVersion must be ${contract.schemaVersion}`
    );
  }
  for (const [field, kind] of Object.entries(contract.fields)) {
    if (
      !valuesAtPath(value, field).every((candidate) =>
        matchesKind(candidate, kind)
      )
    ) {
      throw new TypeError(`${artifactName}: ${field} must be ${kind}`);
    }
  }
  return value as T;
}
