/* eslint-disable react-refresh/only-export-components -- a context or action module exports its components and helpers together */
/**
 * The event being worked on: loaded from IndexedDB for the event in the URL (or, elsewhere, the
 * last one opened), with the write-before-show commit (UISpec.md 6, rules 1 and 2; decision D12).
 *
 * A change is shown only once it is stored. If another tab changed the stored event, the "This
 * event changed in another tab" modal asks whether to load the latest or overwrite it. If storing
 * fails, the change is kept in memory (so the scorer can carry on and download a backup) and the
 * storage status shows the "NOT being saved" alert.
 */
import { Button, Group, Modal, Text } from "@mantine/core";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { useLocation, useMatch } from "react-router";
import type { EventDocument } from "../engine/types";
import { setSessionRoute } from "../storage/autosave";
import type { SaveResult } from "../storage/db";
import { nowIso, useServices } from "./services";
import { useSettings } from "./settings";

export type EventState =
  | { kind: "none" }
  | { kind: "loading"; id: string }
  | { kind: "found"; id: string; doc: EventDocument }
  | { kind: "missing"; id: string }
  | { kind: "corrupt"; id: string; raw: unknown }
  | { kind: "failed"; id: string; message: string };

interface CurrentEventValue {
  state: EventState;
  /** The event id in the URL, or null outside event routes. */
  routeId: string | null;
  /**
   * Store a changed document, then show it.
   *
   * @returns True if the change is now shown (stored, or kept in memory after a storage failure),
   *   false if the user chose to load the other tab's version instead.
   */
  commit: (next: EventDocument) => Promise<boolean>;
  /** Rename the event (D12); same outcome as `commit`. */
  rename: (name: string) => Promise<boolean>;
  /** Delete the event from this browser; true when deleted. */
  remove: () => Promise<boolean>;
  /** Read the event from storage again (after Home renamed or deleted it). */
  reload: () => void;
}

interface PendingConflict {
  next: EventDocument;
  current: EventDocument | null;
  resolve: (shown: boolean) => void;
}

const CurrentEventContext = createContext<CurrentEventValue | null>(null);

/**
 * Provide the current event to the shell and the event views.
 *
 * @param props.children - The app shell.
 * @returns The provider, with the two-tab conflict modal.
 */
export function CurrentEventProvider({ children }: { children: ReactNode }) {
  const { store } = useServices();
  const { settings, update } = useSettings();
  const match = useMatch("/e/:id/*");
  const location = useLocation();
  const routeId = match?.params.id ?? null;
  const activeId = routeId ?? settings.last_event_id;
  const [state, setState] = useState<EventState>({ kind: "none" });
  const [conflict, setConflict] = useState<PendingConflict | null>(null);
  const [loads, setLoads] = useState(0);
  const docRef = useRef<EventDocument | null>(null);
  useEffect(() => {
    docRef.current = state.kind === "found" ? state.doc : null;
  }, [state]);

  // Load the active event whenever it changes. The state mirrors IndexedDB, an external store,
  // so resetting it when the id changes is intended.
  /* eslint-disable react-hooks/set-state-in-effect */
  useEffect(() => {
    if (activeId === null) {
      setState({ kind: "none" });
      return;
    }
    let cancelled = false;
    setState((current) =>
      current.kind === "found" && current.id === activeId
        ? current
        : { kind: "loading", id: activeId },
    );
    void store.loadEvent(activeId).then((result) => {
      if (cancelled) return;
      if (result.status === "found")
        setState({ kind: "found", id: activeId, doc: result.document });
      else if (result.status === "missing") setState({ kind: "missing", id: activeId });
      else if (result.status === "corrupt")
        setState({ kind: "corrupt", id: activeId, raw: result.raw });
      else setState({ kind: "failed", id: activeId, message: result.failure.message });
    });
    return () => {
      cancelled = true;
    };
  }, [activeId, store, loads]);
  /* eslint-enable react-hooks/set-state-in-effect */

  // A remembered event that no longer exists is forgotten quietly.
  useEffect(() => {
    if (routeId === null && state.kind === "missing" && state.id === settings.last_event_id) {
      update({ last_event_id: null });
    }
  }, [routeId, state, settings.last_event_id, update]);

  // Remember the open event and its route, for the Resume card (UISpec.md 6, rule 4).
  const found = state.kind === "found" && state.id === routeId;
  useEffect(() => {
    if (routeId === null || !found) return;
    void setSessionRoute(store, routeId, location.pathname);
    if (settings.last_event_id !== routeId) update({ last_event_id: routeId });
  }, [routeId, found, location.pathname, store, settings.last_event_id, update]);

  const apply = useCallback((result: SaveResult, next: EventDocument): Promise<boolean> => {
    if (result.status === "saved") {
      setState({ kind: "found", id: result.document.id, doc: result.document });
      return Promise.resolve(true);
    }
    if (result.status === "failed") {
      setState({ kind: "found", id: next.id, doc: next }); // the alert offers a backup of it
      return Promise.resolve(true);
    }
    return new Promise((resolve) => setConflict({ next, current: result.current, resolve }));
  }, []);

  const commit = useCallback(
    async (next: EventDocument) => {
      const loaded = docRef.current;
      const result = await store.saveEvent(
        next,
        loaded === null ? null : loaded.revision,
        nowIso(),
      );
      return apply(result, next);
    },
    [store, apply],
  );

  const rename = useCallback(
    async (name: string) => {
      const loaded = docRef.current;
      if (loaded === null) return false;
      const result = await store.renameEvent(loaded.id, name, loaded.revision, nowIso());
      return apply(result, { ...loaded, name });
    },
    [store, apply],
  );

  const remove = useCallback(async () => {
    const loaded = docRef.current;
    const id = loaded?.id ?? activeId;
    if (id === null) return false;
    const result = await store.deleteEvent(id);
    if (result.status !== "deleted") return false;
    if (settings.last_event_id === id) update({ last_event_id: null });
    setState({ kind: "missing", id });
    return true;
  }, [store, activeId, settings.last_event_id, update]);

  async function resolveConflict(choice: "latest" | "overwrite") {
    if (conflict === null) return;
    const { next, current, resolve } = conflict;
    setConflict(null);
    if (choice === "latest") {
      if (current === null) {
        const reloaded = await store.loadEvent(next.id);
        setState(
          reloaded.status === "corrupt"
            ? { kind: "corrupt", id: next.id, raw: reloaded.raw }
            : { kind: "missing", id: next.id },
        );
      } else {
        setState({ kind: "found", id: current.id, doc: current });
      }
      resolve(false);
      return;
    }
    const result = await store.saveEvent(
      next,
      current === null ? null : current.revision,
      nowIso(),
    );
    resolve(await apply(result, next));
  }

  const value = useMemo(
    () => ({ state, routeId, commit, rename, remove, reload: () => setLoads((n) => n + 1) }),
    [state, routeId, commit, rename, remove],
  );

  return (
    <CurrentEventContext.Provider value={value}>
      {children}
      <Modal
        opened={conflict !== null}
        onClose={() => void resolveConflict("latest")}
        title="This event changed in another tab"
        closeOnClickOutside={false}
      >
        <Text size="sm">
          {conflict?.current === null
            ? "Another tab deleted this event, or its saved copy can no longer be read."
            : "Another tab saved a newer version of this event while this tab was open."}{" "}
          Load the latest saved version, or overwrite it with what this tab shows.
        </Text>
        <Group justify="flex-end" mt="md">
          <Button variant="default" onClick={() => void resolveConflict("latest")}>
            Load latest
          </Button>
          <Button color="red" onClick={() => void resolveConflict("overwrite")}>
            Overwrite with this tab
          </Button>
        </Group>
      </Modal>
    </CurrentEventContext.Provider>
  );
}

/**
 * The current event and its actions.
 *
 * @returns The context value.
 */
export function useCurrentEvent(): CurrentEventValue {
  const value = useContext(CurrentEventContext);
  if (value === null) throw new Error("useCurrentEvent needs a CurrentEventProvider.");
  return value;
}
