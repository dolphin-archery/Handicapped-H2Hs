import { useSyncExternalStore } from "react";
import type { EngineClient, EngineStatus } from "./client";

/**
 * The engine's current status, re-rendering on every change.
 *
 * @param engine - The engine client.
 * @returns Its status (idle, loading with a stage, ready with timings, or failed with a message).
 */
export function useEngineStatus(engine: EngineClient): EngineStatus {
  return useSyncExternalStore(
    (onChange) => engine.subscribe(onChange),
    () => engine.getStatus(),
  );
}
