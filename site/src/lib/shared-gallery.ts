import {gallery as native} from './gallery';
import {sharedRows,galleryIdentity} from './shared-archives';
const kinds = ['comics','stamps','stickers','backgrounds'] as const;
const values = await Promise.all(kinds.map(kind=>sharedRows(native[kind], 'projection/gallery.json',kind,galleryIdentity)));
export const gallery = {...native,...Object.fromEntries(kinds.map((kind,index)=>[kind,values[index]]))} as typeof native;
