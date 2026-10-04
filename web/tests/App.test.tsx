import { ModalsProvider } from "@mantine/modals";
import { screen } from "@testing-library/react";
import { IDBFactory } from "fake-indexeddb";
import { describe, expect, it } from "vitest";
import App from "../src/App";
import { ServicesProvider } from "../src/app/services";
import { SettingsProvider } from "../src/app/settings";
import { EngineClient, type WorkerLike } from "../src/engine/client";
import { DEFAULT_SETTINGS } from "../src/storage/autosave";
import { EventStore } from "../src/storage/db";
import { render } from "./render";

/** A worker stand-in that never answers (the engine stays loading). */
function silentWorker(): WorkerLike {
  return { postMessage() {}, terminate() {}, onmessage: null, onerror: null };
}

describe("App", () => {
  it("opens Home in the shell with the engine banner while Python loads", async () => {
    globalThis.indexedDB = new IDBFactory();
    const engine = new EngineClient(silentWorker, "http://localhost/py/h2h-test.zip");
    engine.start();
    const store = new EventStore();
    render(
      <ServicesProvider services={{ engine, store }}>
        <SettingsProvider store={store} initial={DEFAULT_SETTINGS}>
          <ModalsProvider>
            <App />
          </ModalsProvider>
        </SettingsProvider>
      </ServicesProvider>,
    );
    expect(screen.getByRole("heading", { level: 1, name: "Events" })).toBeInTheDocument();
    expect(screen.getByText("Getting the scoring engine ready")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Handicap calculator" })).toBeInTheDocument();
    engine.dispose();
  });
});
