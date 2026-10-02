import type {CardDetailProjection} from './game-database';
import {recordsFromGlob} from './database-records';
export {publicSkills} from './card-list-skills';

export const cardDetailProjections = {
  memberCards:recordsFromGlob<CardDetailProjection>('database-shards/member-cards', 'cardId',
    import.meta.glob('@projection-data/database-shards/member-cards/*.json', {eager:true}))
};
