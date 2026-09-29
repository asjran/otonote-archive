import {parentPort,workerData} from 'node:worker_threads';
globalThis.self={postMessage:data=>parentPort.postMessage(data),addEventListener:(type,handler)=>{if(type==='message')parentPort.on('message',data=>handler({data}));}};
await import(workerData.entry);
