import { optimizeFormations } from "./formation-optimizer.mjs";

export function createFormationOptimizerWorkerController({
  postMessage,
  optimize = optimizeFormations
}) {
  if (typeof postMessage !== "function") {
    throw new TypeError("postMessage adapter is required");
  }
  const active = new Map();

  return {
    async handle(message) {
      const requestId = String(message?.requestId ?? "");
      if (message?.type === "cancel") {
        const controller = active.get(requestId);
        controller?.abort();
        postMessage({
          type: "cancelled",
          requestId,
          active: Boolean(controller)
        });
        return;
      }
      if (message?.type !== "optimize") return;
      const controller = new AbortController();
      active.set(requestId, controller);
      const payload = message.payload ?? {};
      const exactScores = payload.exactScores ?? {};
      try {
        const result = await optimize({
          ...payload,
          signal: controller.signal,
          exactScore(candidate) {
            const score = exactScores[candidate.id];
            if (!Number.isSafeInteger(score)) {
              throw new Error(
                `No reconciled exact score is available for ${candidate.id}`
              );
            }
            return score;
          },
          onProgress(progress) {
            postMessage({ type: "progress", requestId, progress });
          }
        });
        postMessage({ type: "result", requestId, result });
      } catch (error) {
        postMessage({
          type: "error",
          requestId,
          error: error instanceof Error ? error.message : String(error)
        });
      } finally {
        active.delete(requestId);
      }
    }
  };
}

if (
  typeof globalThis.WorkerGlobalScope !== "undefined"
  && globalThis instanceof globalThis.WorkerGlobalScope
) {
  const controller = createFormationOptimizerWorkerController({
    postMessage: (message) => globalThis.postMessage(message)
  });
  globalThis.addEventListener("message", (event) => {
    void controller.handle(event.data);
  });
}
