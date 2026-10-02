/** Append the renderer to an existing sealed release; preserve every page module. */
import {readFile, writeFile, mkdir, cp, readdir} from 'node:fs/promises';
import {resolve, join, relative} from 'node:path';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {buildPrerenderRuntime} from './build_prerender_runtime.mjs';
const [sourceArg, outputArg] = process.argv.slice(2);
if (!sourceArg || !outputArg) throw Error('Usage: enable_prerender_release.mjs BASE NEW_OUTPUT');
const source = resolve(sourceArg), output = resolve(outputArg);
if (!output.startsWith(resolve('output') + '/')) throw Error('Output must be inside output/');
execFileSync('python3', ['-m','tools.code_publication','--source',source,'--verify-only']);
const before = JSON.parse(await readFile(join(source,'code-release.json'),'utf8'));
await mkdir(output);
await cp(join(source,'compiled'),join(output,'compiled'),{recursive:true});
await buildPrerenderRuntime(join(output,'compiled'));
let shell = (await readFile(join(source,'index.html'),'utf8')).replaceAll(before.codeId,'__CODE_ID__');
const navigationScript = await readFile(join(output,'compiled/prerender/navigation.js'),'utf8');
shell = shell.replace(/<script[^>]*data-navigation-client[^>]*>[\s\S]*?<\/script>/g, '');
shell = shell.replace('</body>',`<script data-navigation-client data-code-root="/app/releases/__CODE_ID__/">${navigationScript.replace(/<\/script/gi,'<\\/script')}</script></body>`);
await writeFile(join(output,'compiled/entry-shell.json'),JSON.stringify({sha256:createHash('sha256').update(shell).digest('hex')}));
async function walk(dir) {return (await Promise.all((await readdir(dir,{withFileTypes:true})).map(e => e.isDirectory() ? walk(join(dir,e.name)) : join(dir,e.name)))).flat();}
const files = {};
for (const file of (await walk(join(output,'compiled'))).sort()) files[relative(join(output,'compiled'),file)] = createHash('sha256').update(await readFile(file)).digest('hex');
const codeId = createHash('sha256').update(JSON.stringify(files)).digest('hex').slice(0,24);
await writeFile(join(output,'index.html'),shell.replaceAll('__CODE_ID__',codeId));
await writeFile(join(output,'code-release.json'),JSON.stringify({schemaVersion:1,codeId,contentSchemaVersion:1,files},null,2));
execFileSync('python3',['-m','tools.code_publication','--source',output,'--verify-only']);
console.log(JSON.stringify({baseCodeId:before.codeId,codeId,output}));
