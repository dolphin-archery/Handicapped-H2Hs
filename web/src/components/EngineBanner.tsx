import { Alert, Button, Group, Progress, Text } from "@mantine/core";
import type { EngineClient } from "../engine/client";
import type { LoadStage } from "../engine/host";
import { useEngineStatus } from "../engine/useEngineStatus";

/** What each load stage is doing, and how far along engine start it roughly is. */
const STAGES: Record<LoadStage, { text: string; value: number }> = {
  runtime: { text: "Starting Python", value: 15 },
  packages: { text: "Loading the statistics packages", value: 45 },
  pdf: { text: "Loading the PDF export", value: 70 },
  app: { text: "Loading the app's own code", value: 90 },
};

/**
 * The engine's start-up and failure banner (UISpec.md 7.6). Non-blocking: saved events and the
 * forms stay usable while Python loads; actions that need it show their own loading state. Hidden
 * once the engine is ready.
 *
 * @param props.engine - The engine client.
 * @returns The banner, or nothing when the engine is ready (or not started).
 */
export function EngineBanner({ engine }: { engine: EngineClient }) {
  const status = useEngineStatus(engine);
  if (status.state === "loading") {
    const stage = STAGES[status.stage];
    return (
      <Alert variant="light" color="blue" mb="md" title="Getting the scoring engine ready">
        <Text size="sm" aria-live="polite">
          {stage.text}... The first visit downloads about 12 MB; later visits are faster. You can
          look at saved events meanwhile.
        </Text>
        <Progress
          value={stage.value}
          mt="xs"
          size="sm"
          animated
          aria-label="Engine start progress"
        />
      </Alert>
    );
  }
  if (status.state === "failed") {
    return (
      <Alert
        variant="light"
        color="red"
        mb="md"
        title="The scoring engine could not start"
        role="alert"
      >
        <Text size="sm">
          {status.message} This can happen offline on a first visit. Your saved events are not
          affected.
        </Text>
        <Group mt="xs">
          <Button size="xs" variant="filled" color="red" onClick={() => engine.start()}>
            Retry
          </Button>
          <Button size="xs" variant="default" onClick={() => window.location.reload()}>
            Reload the page
          </Button>
        </Group>
      </Alert>
    );
  }
  return null;
}
