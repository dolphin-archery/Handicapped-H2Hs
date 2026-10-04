/* eslint-disable react-refresh/only-export-components -- a context or action module exports its components and helpers together */
/**
 * Device settings (UISpec.md 6: colour scheme, graph view, last opened event), held in React state
 * and written through to IndexedDB; plus the Mantine colour-scheme manager that reads and writes
 * the colour scheme there instead of Mantine's default localStorage key (decision D8).
 */
import type { MantineColorScheme, MantineColorSchemeManager } from "@mantine/core";
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { updateSettings, type Settings } from "../storage/autosave";
import type { EventStore } from "../storage/db";

interface SettingsValue {
  settings: Settings;
  /** Change some settings (applied at once; stored in the background). */
  update: (changes: Partial<Settings>) => void;
}

const SettingsContext = createContext<SettingsValue | null>(null);

/**
 * Provide the device settings, starting from those read at start-up.
 *
 * @param props.store - The event store the settings live in.
 * @param props.initial - The settings read before the first render.
 * @param props.children - The app.
 * @returns The provider.
 */
export function SettingsProvider({
  store,
  initial,
  children,
}: {
  store: EventStore;
  initial: Settings;
  children: ReactNode;
}) {
  const [settings, setSettings] = useState(initial);
  const update = useCallback(
    (changes: Partial<Settings>) => {
      setSettings((current) => ({ ...current, ...changes }));
      void updateSettings(store, changes);
    },
    [store],
  );
  const value = useMemo(() => ({ settings, update }), [settings, update]);
  return <SettingsContext.Provider value={value}>{children}</SettingsContext.Provider>;
}

/**
 * The device settings.
 *
 * @returns The settings and a function to change them.
 */
export function useSettings(): SettingsValue {
  const value = useContext(SettingsContext);
  if (value === null) throw new Error("useSettings needs a SettingsProvider.");
  return value;
}

/**
 * A Mantine colour-scheme manager backed by the app's settings record.
 *
 * Mantine reads the scheme synchronously, so the manager starts from the value read before the
 * first render and writes changes to IndexedDB in the background.
 *
 * @param store - The event store.
 * @param initial - The colour scheme read at start-up.
 * @returns The manager for `MantineProvider`.
 */
export function settingsColorSchemeManager(
  store: EventStore,
  initial: MantineColorScheme,
): MantineColorSchemeManager {
  let current = initial;
  return {
    get: () => current,
    set: (value) => {
      current = value;
      void updateSettings(store, { color_scheme: value });
    },
    subscribe: () => {},
    unsubscribe: () => {},
    clear: () => {},
  };
}
