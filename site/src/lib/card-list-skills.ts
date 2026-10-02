import type {SkillDefinition} from './game-database';
import {recordsFromGlob} from './database-records';

export const publicSkills = recordsFromGlob<SkillDefinition>('database-shards/skills', 'id',
  import.meta.glob('@projection-data/database-shards/skills/*.json', {eager:true}));
