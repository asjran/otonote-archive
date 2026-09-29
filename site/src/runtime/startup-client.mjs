import {startPageInputs} from './startup.mjs';

const app = globalThis[Symbol.for('ournotes.code-manifest.v1')];
startPageInputs(app, new URL(app.root, location.href).href);
