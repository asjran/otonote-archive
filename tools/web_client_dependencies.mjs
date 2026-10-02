import {resolve} from 'node:path';

/** Describe only the static data dependencies of each compiled page. */
export function attachDataProfiles(manifest, metafile, groupsByInput, cwd = process.cwd()) {
  const outputs = new Map(Object.entries(metafile.outputs).map(([name, value]) => [resolve(cwd, name), value]));
  const profiles = [], identities = new Map();
  for (const route of manifest.routes) {
    const files = new Set(), groups = new Set(), visited = new Set();
    const visit = name => {
      if (visited.has(name)) return;
      visited.add(name);
      const output = outputs.get(name);
      if (!output) throw new Error('Missing compiled page dependency: ' + name);
      for (const input of Object.keys(output.inputs)) {
        if (input.startsWith('content:')) files.add(input.slice('content:'.length));
        for (const group of groupsByInput.get(resolve(cwd, input)) ?? []) groups.add(group);
      }
      for (const dependency of output.imports) {
        // Lazy players and workers are not prerequisites for the first render.
        if (!dependency.external && dependency.kind === 'import-statement') visit(resolve(cwd, dependency.path));
      }
    };
    visit(resolve(manifest.buildRoot, route.module));
    const profile = {files:[...files].sort(), groups:[...groups].sort()};
    const identity = JSON.stringify(profile);
    if (!identities.has(identity)) { identities.set(identity, profiles.length); profiles.push(profile); }
    route.dataProfile = identities.get(identity);
  }
  manifest.dataProfiles = profiles;
  delete manifest.buildRoot;
}
