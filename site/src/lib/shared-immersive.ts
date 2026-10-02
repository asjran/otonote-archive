import native from '../data/immersive-scenes.json';
import {sharedRows} from './shared-archives';
type Scene = typeof native.scenes[number] & {contentIdentity?:string; sourceHref?:string; editionPresence?:{status:string;editions:string[]}};
const scenes=await sharedRows(native.scenes as Scene[],'supplemental/immersive-scenes.json','scenes',
  row=>row.contentIdentity??null,row=>`/immersive/${row.id}/`);
export default {...native,scenes};
