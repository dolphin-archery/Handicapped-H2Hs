import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import App from "../src/App";
import { render } from "./render";

describe("App", () => {
  it("shows the app title as the page heading", () => {
    render(<App />);
    expect(screen.getByRole("heading", { level: 1, name: "Handicapped H2Hs" })).toBeInTheDocument();
  });
});
