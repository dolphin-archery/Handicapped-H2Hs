import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import App from "../src/App";
import { EngineClient, type WorkerLike } from "../src/engine/client";
import { render } from "./render";

/** A worker stand-in that never answers (the engine stays loading). */
function silentWorker(): WorkerLike {
  return { postMessage() {}, terminate() {}, onmessage: null, onerror: null };
}

describe("App", () => {
  it("shows the app title as the page heading and starts the engine", () => {
    const engine = new EngineClient(silentWorker, "http://localhost/py/h2h-test.zip");
    render(<App engine={engine} />);
    expect(screen.getByRole("heading", { level: 1, name: "Handicapped H2Hs" })).toBeInTheDocument();
    expect(screen.getByTestId("engine-status")).toHaveTextContent("Engine: starting Python...");
    engine.dispose();
  });
});
