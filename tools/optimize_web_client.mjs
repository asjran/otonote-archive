#!/usr/bin/env node
/** Apply loading fixes to a verified published bundle, without deploying other workspace changes. */
import {readFile, writeFile, mkdir, cp, readdir} from 'node:fs/promises';
import {resolve, dirname, relative, join} from 'node:path';
import {fileURLToPath} from 'node:url';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {build} from '../site/node_modules/esbuild/lib/main.js';
import {init, parse} from '../site/node_modules/es-module-lexer/dist/lexer.js';
import {attachDataProfiles} from './web_client_dependencies.mjs';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const [sourceArg, outputArg] = process.argv.slice(2);
if (!sourceArg || !outputArg) throw Error('Usage: optimize_web_client.mjs BASE_RELEASE NEW_OUTPUT');
const source = resolve(sourceArg), output = resolve(outputArg);
if (!output.startsWith(join(root, 'output') + '/')) throw Error('Output must be under output/');
execFileSync('python3', ['-m', 'tools.code_publication', '--source', source, '--verify-only'], {cwd:root});
const previous = JSON.parse(await readFile(join(source, 'code-release.json'), 'utf8'));
await mkdir(output);
await cp(join(source, 'compiled'), join(output, 'compiled'), {recursive:true});
const compiled = join(output, 'compiled');
const app = JSON.parse(await readFile(join(compiled, 'manifest.json'), 'utf8'));
await init;
const groupsByInput = new Map();
const patched = [];

for (const [kind, collection, field] of [['members', 'member-cards', 'memberCards'], ['supports', 'support-cards', 'supportCards']]) {
  const route = app.routes.find(item => item.pattern === 'cards/' + kind);
  if (!route) throw Error('Missing card list route');
  const filename = join(compiled, route.module);
  let page = await readFile(filename, 'utf8');
  const imports = parse(page)[0];
  let database;
  for (const dependency of imports.filter(item => item.d === -1 && item.n?.startsWith('.'))) {
    const path = resolve(dirname(filename), dependency.n);
    const code = await readFile(path, 'utf8');
    if (code.includes('cardDetailProjections:()=>') && code.includes('publicSkills:()=>')) {
      if (database) throw Error('Ambiguous card database dependency');
      database = {dependency, code};
    }
  }
  if (!database) throw Error('Published card list has no recognized database dependency');
  const exports = parse(database.code)[1];
  const alias = property => {
    const local = database.code.match(new RegExp(property + ':\\(\\)=>\\s*([\\w$]+)'))?.[1];
    const name = exports.find(item => item.ln === local)?.n;
    if (!name) throw Error('Missing published export: ' + property);
    return name;
  };
  const cardAlias = alias('cardDetailProjections'), skillAlias = alias('publicSkills');
  const namespaceLocal = database.code.match(/(?:var|let|const) ([\w$]+)=\{\};[\w$]+\(\1,\{cardDetailProjections:/)?.[1];
  const namespaceAlias = exports.find(item => item.ln === namespaceLocal)?.n;
  if (!namespaceAlias) throw Error('Missing published database namespace');
  const groupNames = ['@projection-data/database-shards/skills/*.json', `@projection-data/database-shards/${collection}/*.json`];
  const result = await build({
    stdin:{contents:`import {artifactGlob} from './site/src/runtime/content.mjs';
      import {recordsFromGlob} from './site/src/lib/database-records.ts';
      const [skills, cards] = await Promise.all(${JSON.stringify(groupNames)}.map(name => artifactGlob(name)));
      const publicSkills = recordsFromGlob('database-shards/skills', 'id', skills);
      const cardDetailProjections = {${field}:recordsFromGlob('database-shards/${collection}', 'cardId', cards)};
      const namespace = {publicSkills, cardDetailProjections};
      export {cardDetailProjections as ${cardAlias}, publicSkills as ${skillAlias}, namespace as ${namespaceAlias}};`, resolveDir:root},
    bundle:true, write:false, minify:true, format:'esm', target:'es2022'
  });
  const bytes = result.outputFiles[0].contents;
  const name = 'chunks/card-list-' + kind + '-' + createHash('sha256').update(bytes).digest('hex').slice(0,12) + '.js';
  await writeFile(join(compiled, name), bytes);
  groupsByInput.set(join(compiled, name), groupNames);
  const replacement = relative(dirname(filename), join(compiled, name));
  page = page.slice(0, database.dependency.s) + replacement + page.slice(database.dependency.e);
  const pageName = 'pages/cards_' + kind + '_index-' + createHash('sha256').update(page).digest('hex').slice(0,12) + '.js';
  await writeFile(join(compiled, pageName), page);
  route.module = pageName;
  patched.push({route:route.pattern, from:relative(compiled, filename), to:pageName, dataModule:name});
}

// Reconstruct the static import graph from the sealed bundle. Runtime/lazy
// imports are excluded; only literal awaited content inputs are warmed.
const metafile = {outputs:{}};
async function describe(filename) {
  if (metafile.outputs[filename]) return;
  if (!filename.startsWith(compiled + '/')) throw Error('Dependency escaped compiled release');
  const code = await readFile(filename, 'utf8');
  const dependencies = parse(code)[0].filter(item => item.d === -1 && item.n?.startsWith('.'));
  const inputs = {[filename]:{}};
  const groups = new Set(groupsByInput.get(filename) ?? []);
  for (const match of code.matchAll(/await\s+[\w$]+\("((?:projection\/|supplemental\/|public\/|@projection-data\/)[^"]+\.json)"/g)) {
    if (match[1].startsWith('@projection-data/')) groups.add(match[1]);
    else inputs['content:' + match[1]] = {};
  }
  groupsByInput.set(filename, [...groups]);
  metafile.outputs[filename] = {inputs, imports:dependencies.map(item => ({path:resolve(dirname(filename), item.n), kind:'import-statement'}))};
  for (const dependency of metafile.outputs[filename].imports) await describe(dependency.path);
}
for (const route of app.routes) await describe(join(compiled, route.module));
app.buildRoot = compiled;
attachDataProfiles(app, metafile, groupsByInput);
await writeFile(join(compiled, 'manifest.json'), JSON.stringify(app));
const starter = await build({entryPoints:[join(root, 'site/src/runtime/startup-client.mjs')], bundle:true, write:false, minify:true, format:'iife', target:'es2022'});
let shell = (await readFile(join(source, 'index.html'), 'utf8')).replaceAll(previous.codeId, '__CODE_ID__');
const marker = /<script>globalThis\[Symbol\.for\('ournotes\.code-manifest\.v1'\)\][\s\S]*?<\/script>/g;
if ([...shell.matchAll(marker)].length !== 1) throw Error('Expected one inline startup in published shell');
const script = `globalThis[Symbol.for('ournotes.code-manifest.v1')]=${JSON.stringify({...app, root:'/app/releases/__CODE_ID__/'})};${starter.outputFiles[0].text}`;
shell = shell.replace(marker, () => '<script>' + script.replace(/</g, '\\u003c') + '</script>');
await writeFile(join(compiled, 'entry-shell.json'), JSON.stringify({sha256:createHash('sha256').update(shell).digest('hex')}));
async function walk(path) { return (await Promise.all((await readdir(path, {withFileTypes:true})).map(entry => entry.isDirectory() ? walk(join(path, entry.name)) : join(path, entry.name)))).flat(); }
const files = {};
for (const file of (await walk(compiled)).sort()) files[relative(compiled, file)] = createHash('sha256').update(await readFile(file)).digest('hex');
const codeId = createHash('sha256').update(JSON.stringify(files)).digest('hex').slice(0,24);
await writeFile(join(output, 'index.html'), shell.replaceAll('__CODE_ID__', codeId));
await writeFile(join(output, 'code-release.json'), JSON.stringify({schemaVersion:1, codeId, contentSchemaVersion:1, files}, null, 2));
execFileSync('python3', ['-m', 'tools.code_publication', '--source', output, '--verify-only'], {cwd:root});
console.log(JSON.stringify({baseCodeId:previous.codeId, codeId, patched, profiles:app.dataProfiles.length, output}, null, 2));
