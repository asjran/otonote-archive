import type {CardDetailProjection} from './game-database';
import {recordsFromGlob} from './database-records';
export {publicSkills} from './card-list-skills';

export const cardDetailProjections = {
  supportCards:recordsFromGlob<CardDetailProjection>('database-shards/support-cards', 'cardId',
    import.meta.glob('@projection-data/database-shards/support-cards/*.json', {eager:true}))
};
