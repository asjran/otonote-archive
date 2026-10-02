import {catalog as nativeCatalog} from './catalog';
import {otherEditionArtifact} from '../runtime/content.mjs';
import {mergeCatalogs} from './edition-library.mjs';
export * from './catalog';
const secondary = await otherEditionArtifact(nativeCatalog.release.region, 'projection/catalog.json');
export const catalog = mergeCatalogs(nativeCatalog, secondary, nativeCatalog.release.locale) as typeof nativeCatalog;
// Native detail and tool models remain bound to their own snapshot. Tiles can
// resolve explicitly namespaced references from the shared directory.
Reflect.set(globalThis, Symbol.for('ournotes.library.catalog.v1'), catalog);
