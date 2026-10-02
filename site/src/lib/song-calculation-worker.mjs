import {createFormalSongCalculator} from './scoring-rules/formal-song-score.mjs';
import {createGekisouSongCalculator} from './scoring-rules/gekisou-song-score.mjs';
import {createPerformanceSongCalculator} from './scoring-rules/formal-performance-replay.mjs';
self.addEventListener('message',({data})=>{
  try {
    if(data.mode==='gekisou' && data.performance) throw new Error('逐音符判定回放目前支持普通演出；激奏使用页面上的 AP 情景。');
    const calculator=data.mode==='gekisou'?createGekisouSongCalculator(data.rules,data.chart,{scenario:data.scenario}):data.performance
      ?createPerformanceSongCalculator(data.rules,data.chart,{performance:data.performance}):createFormalSongCalculator(data.rules,data.chart);
    self.postMessage({result:calculator.calculate(data.draft,{includeTrace:true})});
  }catch(error){self.postMessage({error:String(error.message??error)});}
});
