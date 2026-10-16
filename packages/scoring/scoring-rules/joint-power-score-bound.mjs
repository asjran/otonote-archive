/** Safe joint power/skill relaxation for ideal ordinary scoring.
 * Each edge retains both its power and effective skill. Character/position
 * assignment and optional support prices bound the full legal problem without
 * enumerating complete teams. Native rounding is covered by the caller's
 * coefficient and replay-error bounds; this module never supplies a score.
 */
export function createJointPowerScoreBound({coefficients,spans,profileFor,metric}) {
  let jointLinear = null;
  if (coefficients?.length && coefficients.length<=100000 && coefficients.every(v => Number.isFinite(v) && v >= 0)) {
    const prefix = [0];for (const value of coefficients) prefix.push(prefix.at(-1) + value);
    const total = prefix.at(-1), n = coefficients.length + 1, epsilon = total * 2 * n * 2 ** -53 / (1 - n * 2 ** -53);
    jointLinear = {total:total + epsilon, gains:new Map([...spans].map(([signature, positions]) => [signature,
      positions.map(effects => effects.reduce((sum,e) => sum + Math.max(0,prefix[e.last]-prefix[e.first]+epsilon)*e.value,0))]))};
  }
  if (!jointLinear) return null;
  // S <= P*H. For any positive lambda, 4*lambda*P*H <=
  // (lambda*P+H)^2. Maximize that LINEAR sum over character/skill-position
  // assignments, keeping each pair's power and skill together. This relaxes
  // support uniqueness but never combines one pair's power with another's
  // skill. Every lambda is independently safe; iterations only tighten it.
  return (available, forced, leader, solution, error, priceSupports) => {
    const maximumPower=solution.weight;
    if (!jointLinear || maximumPower <= 0) return Infinity;
    const compulsory = new Map(forced.map(e => [e.character,e]));
    const leaderCharacter = available.find(e => e.member === leader)?.character;
    const groups = new Map();
    for (const e of available) {
      const fixed = compulsory.get(e.character);
      if (fixed && fixed.key !== e.key || e.character === leaderCharacter && e.member !== leader) continue;
      let group = groups.get(e.character);
      if (!group) groups.set(e.character,group={mandatory:Boolean(fixed)||e.character===leaderCharacter,profiles:new Map(),edges:[]});
      group.edges.push(e);
      const profile = profileFor(e), previous = group.profiles.get(profile);
      if (!previous || e.weight > previous.weight) group.profiles.set(profile,e);
    }
    const base = jointLinear.total * (1 + error);
    let largestPower=0,largestGain=0;
    for(const e of available)largestPower=Math.max(largestPower,Math.abs(e.weight));
    for(const gains of jointLinear.gains.values())for(const gain of gains)largestGain=Math.max(largestGain,gain);
    const roundedUpper=(sum,lambda,prices)=>{
      let priceSum=0,largestPrice=0;
      for(const price of prices?.values()??[]){priceSum+=Math.abs(price);largestPrice=Math.max(largestPrice,Math.abs(price));}
      // Priced edges may be negative. Bound absolute operand magnitudes,
      // rather than inflating a small result after cancellation. At most
      // five edges are added by the DP; every price is added once outside it.
      const scale=base+5*(lambda*largestPower+largestGain+largestPrice)+priceSum;
      const outward=Math.max(0,sum)+scale*1e-10;
      return Math.ceil(outward*outward/(4*lambda)*(1+1e-10));
    };
    let lambda = base / maximumPower, upper = Infinity, bestLambda=lambda;
    const assign = (lambda, prices) => {
      let dp = Array(32).fill(null);dp[0] = {value:0,power:0,gain:0};
      for (const group of groups.values()) {
        const choices = Array(5).fill(null);
        for (const e of prices ? group.edges : group.profiles.values()) {
          const profile=profileFor(e);
          const gains = jointLinear.gains.get(profile.signature);
          const mean = gains.reduce((a,b) => a+b,0)/5;
          for (let i=0;i<5;i++) {
            const gain = metric === 'maximumScore' ? gains[i] : mean, value = lambda*e.weight+gain-(prices?.get(e.support)??0);
            if (!choices[i] || value > choices[i].value) choices[i] = {value,power:e.weight,gain,edge:e};
          }
        }
        const next = group.mandatory ? Array(32).fill(null) : [...dp];
        for (let mask=0;mask<32;mask++) if (dp[mask]) for (let i=0;i<5;i++) if (!(mask&(1<<i)) && choices[i]) {
          const target=mask|(1<<i),a=dp[mask],b=choices[i],value=a.value+b.value;
          if (!next[target] || value > next[target].value) next[target]={value,power:a.power+b.power,gain:a.gain+b.gain,previous:a,edge:b.edge};
        }
        dp=next;
      }
      return dp[31];
    };
    for (let iteration = 0; iteration < 4; iteration++) {
      const chosen=assign(lambda);if(!chosen)return Infinity;
      const sum=base+chosen.value;
      const value=roundedUpper(sum,lambda);
      if(value<upper){upper=value;bestLambda=lambda;}
      const next=(base+chosen.gain)/chosen.power;
      if (!Number.isFinite(next)||next<=0||Math.abs(next-lambda)<=lambda*1e-6)break;
      lambda=next;
    }
    if (priceSupports) {
      lambda=bestLambda;
      // Feasible matching gives a lower bound for this LINEAR objective (not
      // for native score). Its optimal five-position assignment is tiny.
      let feasible=Array(32).fill(-Infinity);feasible[0]=0;
      for(const e of solution.edges){
        const gains=jointLinear.gains.get(profileFor(e).signature),mean=gains.reduce((a,b)=>a+b,0)/5,next=Array(32).fill(-Infinity);
        for(let mask=0;mask<32;mask++)if(Number.isFinite(feasible[mask]))for(let i=0;i<5;i++)if(!(mask&(1<<i)))
          next[mask|(1<<i)]=Math.max(next[mask|(1<<i)],feasible[mask]+(metric==='maximumScore'?gains[i]:mean));
        feasible=next;
      }
      const lower=base+lambda*maximumPower+feasible[31],prices=new Map();
      for(let iteration=0;iteration<12;iteration++){
        const chosen=assign(lambda,prices);if(!chosen)break;
        const sum=base+chosen.value+[...prices.values()].reduce((a,b)=>a+b,0);
        upper=Math.min(upper,roundedUpper(sum,lambda,prices));
        const usage=new Map();for(let p=chosen;p.edge;p=p.previous)usage.set(p.edge.support,(usage.get(p.edge.support)??0)+1);
        if([...usage.values()].every(n=>n===1))break;
        const supports=new Set([...prices.keys(),...usage.keys()]);
        let norm=0;for(const s of supports){const d=(usage.get(s)??0)-1;if(d>0||prices.get(s)>0)norm+=d*d;}
        const step=.7*Math.max(0,sum-lower)/Math.max(1,norm);
        if(step<1e-12)break;
        for(const s of supports)prices.set(s,Math.max(0,(prices.get(s)??0)+step*((usage.get(s)??0)-1)));
      }
    }
    return upper;
  };
}
