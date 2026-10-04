import { Container, Text, Title } from "@mantine/core";
import { useEffect, useState } from "react";
import type { EngineClient, EngineStatus } from "./engine/client";
import { useEngineStatus } from "./engine/useEngineStatus";

const STAGE_TEXT = {
  runtime: "starting Python",
  packages: "loading the statistics packages",
  pdf: "loading the PDF export",
  app: "loading the app's Python code",
} as const;

/**
 * One line describing the engine's state (temporary: the app shell's loading banner, task UI-9,
 * replaces it).
 *
 * @param status - The engine status.
 * @returns The text to show.
 */
function statusText(status: EngineStatus): string {
  switch (status.state) {
    case "idle":
      return "Engine: not started.";
    case "loading":
      return `Engine: ${STAGE_TEXT[status.stage]}...`;
    case "ready":
      return `Engine ready in ${(status.timings.total_ms / 1000).toFixed(1)} s.`;
    case "failed":
      return `Engine failed: ${status.message}`;
  }
}

/**
 * Placeholder page shown until the app shell (task UI-9) replaces it. Starts the Python engine in
 * the background and shows its progress.
 *
 * @param props.engine - The engine client to start and watch.
 * @returns The page content; main.tsx renders it inside MantineProvider.
 */
export default function App({ engine }: { engine: EngineClient }) {
  const status = useEngineStatus(engine);
  const [check, setCheck] = useState("");
  useEffect(() => engine.start(), [engine]);
  useEffect(() => {
    // One round trip through the bridge once ready, to show the engine answers (temporary).
    if (status.state !== "ready") return;
    void engine.call("options", {}).then((result) => {
      if (result.ok) setCheck(`Bowstyles: ${result.data.bowstyles.join(", ")}.`);
    });
  }, [engine, status.state]);
  return (
    <Container component="main" size="md" py="xl">
      <Title order={1}>Handicapped H2Hs</Title>
      <Text mt="sm">The new web app is being built.</Text>
      <Text
        mt="sm"
        c="dimmed"
        aria-live="polite"
        data-testid="engine-status"
        data-state={status.state}
        data-timings={status.state === "ready" ? JSON.stringify(status.timings) : undefined}
      >
        {statusText(status)}
      </Text>
      {check && (
        <Text c="dimmed" data-testid="engine-check">
          {check}
        </Text>
      )}
    </Container>
  );
}
