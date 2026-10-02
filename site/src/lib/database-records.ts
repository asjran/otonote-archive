import {validateArtifact} from './artifact-contracts';

/** Validate a collection without importing the rest of the game database. */
export function recordsFromGlob<T>(collection: string, idField: 'id' | 'cardId', modules: Record<string, unknown>): T[] {
  return Object.entries(modules).map(([path, module]) => {
    if (typeof module !== 'object' || module === null || !('default' in module)) {
      throw new TypeError(`${collection}:${path}: default must be an object`);
    }
    return validateArtifact<{schemaVersion:1; record:T}>(`${collection}:${path}`, module.default, {
      schemaVersion:1,
      fields:{contentReleaseId:'string', kind:'string', recordCount:'number', sha256:'string', record:'object', [`record.${idField}`]:'string'}
    }).record;
  });
}
