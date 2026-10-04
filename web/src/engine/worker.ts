/**
 * The engine's module Web Worker (UISpec.md 4; deploymentConstrains 3, rule 3).
 *
 * Loads Pyodide from jsDelivr, pinned to the same release as the `pyodide` npm package (decision
 * D15), then hands every message to the engine host. Pyodide's loader is imported from the CDN
 * at run time rather than bundled, so the loader and its WebAssembly always match.
 */
import requirementsText from "../../pyodide-requirements.txt?raw";
import {
  createEngineHost,
  parseRequirements,
  PYODIDE_CDN,
  type FromEngine,
  type ToEngine,
} from "./host";

/** The parts of the worker's global scope used here (the app's TypeScript lib is DOM, not WebWorker). */
const scope = self as unknown as {
  postMessage(message: FromEngine): void;
  onmessage: ((event: MessageEvent<ToEngine>) => void) | null;
};

const handle = createEngineHost({
  loadPyodide: async (options) => {
    const module = (await import(
      /* @vite-ignore */ `${PYODIDE_CDN}pyodide.mjs`
    )) as typeof import("pyodide");
    return module.loadPyodide(options);
  },
  indexURL: PYODIDE_CDN,
  requirements: parseRequirements(requirementsText),
  fetchBundle: async (url) => {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`Could not download the Python code (${response.status}).`);
    return response.arrayBuffer();
  },
  post: (message) => scope.postMessage(message),
});

scope.onmessage = (event) => {
  void handle(event.data);
};
