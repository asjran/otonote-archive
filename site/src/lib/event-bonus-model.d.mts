import type { EventDefinition } from './event-archive';
type Effect = EventDefinition['effects'][number];
export function groupEventBonuses(effects: Effect[]): {constraints: Effect['constraints']; names: string[]; effects: Effect[]; kind:'card'|'band'|'attribute'|'other'}[];
export function eventBonusPercentage(value: number | null | undefined): number | null;
