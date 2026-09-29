import { readFile } from 'node:fs/promises';
import { SkeletonBinary, SkeletonJson, AtlasAttachmentLoader, TextureAtlas } from '../site/node_modules/@esotericsoftware/spine-core/dist/index.js';
const [file, atlasFile, format] = process.argv.slice(2);
const atlas = new TextureAtlas(await readFile(atlasFile, 'utf8'));
const loader = new AtlasAttachmentLoader(atlas);
const parser = format === 'binary' ? new SkeletonBinary(loader) : new SkeletonJson(loader);
const bytes = await readFile(file);
const data = parser.readSkeletonData(format === 'binary' ? bytes : JSON.parse(bytes));
console.log(JSON.stringify(Object.fromEntries(data.animations.map(a => [a.name, a.duration]))));
