import {createFormalSongCalculator} from './scoring-rules/formal-song-score.mjs';
import {createGekisouSongCalculator} from './scoring-rules/gekisou-song-score.mjs';
self.addEventListener('message',({data})=>{
  try {
    const calculator=data.mode==='gekisou'?createGekisouSongCalculator(data.rules,data.chart,{scenario:data.scenario}):createFormalSongCalculator(data.rules,data.chart);
    self.postMessage({result:calculator.calculate(data.draft,{includeTrace:true})});
  }catch(error){self.postMessage({error:String(error.message??error)});}
});
