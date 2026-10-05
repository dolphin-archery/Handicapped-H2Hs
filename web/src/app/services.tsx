/* eslint-disable react-refresh/only-export-components -- a context or action module exports its components and helpers together */
/**
 * The app's long-lived services, shared through React context so tests can supply their own:
 * the Python engine client and the IndexedDB event store.
 */
import { createContext, useContext, type ReactNode } from "react";
import type { EngineClient } from "../engine/client";
import type { EventStore } from "../storage/db";

export interface Services {
  engine: EngineClient;
  store: EventStore;
}

const ServicesContext = createContext<Services | null>(null);

/**
 * Provide the services to the app.
 *
 * @param props.services - The engine client and the event store.
 * @param props.children - The app.
 * @returns The provider.
 */
export function ServicesProvider({
  services,
  children,
}: {
  services: Services;
  children: ReactNode;
}) {
  return <ServicesContext.Provider value={services}>{children}</ServicesContext.Provider>;
}

/**
 * The app's services.
 *
 * @returns The engine client and the event store.
 */
export function useServices(): Services {
  const services = useContext(ServicesContext);
  if (services === null) throw new Error("useServices needs a ServicesProvider.");
  return services;
}

/**
 * The current time for stored timestamps (`updated_at`, backup times).
 *
 * @returns An ISO-8601 UTC string.
 */
export function nowIso(): string {
  return new Date().toISOString();
}
