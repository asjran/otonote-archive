// A cycle shares the player's collection, not a selected formation or grade.
// Keep old callers compatible while allowing each stage its own constraints.
export function eventYieldStageInput(input,mode){
 if(mode!=='challenge'||input.mode!=='ordinary'||!input.includeChallenge)return {...input,mode};
 return {...input,mode,scope:input.challengeScope&&input.challengeScope!=='same'?input.challengeScope:input.scope,
   basis:input.challengeBasis??input.basis};
}
