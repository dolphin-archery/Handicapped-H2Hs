import { useEffect, useState } from "react";
import { useServices } from "../app/services";
import { EngineError } from "./client";
import type { BridgeError, CommandName, PayloadOf, ResultOf } from "./types";

/** A read-only bridge call's state: waiting, its data, or why it failed. */
export type Query<T> =
  { state: "loading" } | { state: "ok"; data: T } | { state: "error"; error: BridgeError };

/**
 * Run a read-only bridge command (options, pairings, overview, results...) and keep its answer.
 * It runs again whenever the payload changes (compared as JSON, so a new document revision
 * reruns it); an engine failure becomes an `internal` error with the engine's message.
 *
 * @param command - The bridge command.
 * @param payload - Its payload, or null to wait (e.g. until the document has loaded).
 * @param keepPrevious - While a new payload's answer is on its way, keep returning the last
 *   successful answer instead of "loading" (so a form is not unmounted after a save).
 * @returns The query state for this payload.
 */
export function useBridgeQuery<C extends CommandName>(
  command: C,
  payload: PayloadOf<C> | null,
  keepPrevious = false,
): Query<ResultOf<C>> {
  const { engine } = useServices();
  const key = payload === null ? null : `${command}:${JSON.stringify(payload)}`;
  const [answer, setAnswer] = useState<{ key: string; query: Query<ResultOf<C>> } | null>(null);

  useEffect(() => {
    if (key === null || payload === null) return;
    let cancelled = false;
    engine.call(command, payload).then(
      (envelope) => {
        if (cancelled) return;
        const query: Query<ResultOf<C>> = envelope.ok
          ? { state: "ok", data: envelope.data }
          : { state: "error", error: envelope.error };
        setAnswer({ key, query });
      },
      (error: unknown) => {
        if (cancelled) return;
        const message = error instanceof EngineError ? error.message : String(error);
        setAnswer({ key, query: { state: "error", error: { code: "internal", message } } });
      },
    );
    return () => {
      cancelled = true;
    };
    // `key` stands for the command and payload.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [engine, key]);

  if (answer !== null && (answer.key === key || (keepPrevious && answer.query.state === "ok"))) {
    return answer.query;
  }
  return { state: "loading" };
}
