import { activeReleaseContext } from './release-context';

export interface BgmTrack {
  id: string;
  title: string;
  cueName: string;
  categoryIds: string[];
  classificationConfirmed: boolean;
  status: 'available' | 'missing';
  audio: { url: string; duration: number; format: string; byteSize: number; sha256: string } | null;
  downloadName: string;
  sourceAsset: string;
  cueSheet: string;
}
interface BgmCatalog {
  schemaVersion: number;
  sourceReleaseId: string;
  locale: string;
  categories: { id: string; label: string; description: string }[];
  tracks: BgmTrack[];
}
const files = import.meta.glob<BgmCatalog>('@projection-data/bgm.json', { eager: true, import: 'default' });
export const bgmCatalog = Object.values(files)[0];
if (!bgmCatalog || bgmCatalog.schemaVersion !== 1
  || bgmCatalog.sourceReleaseId !== activeReleaseContext.contentReleaseId
  || bgmCatalog.locale !== activeReleaseContext.locale) {
  throw new Error('BGM catalog is missing or does not match the selected release and locale; run the catalog builder');
}
export const isBgmEnglish = activeReleaseContext.locale === 'en';
