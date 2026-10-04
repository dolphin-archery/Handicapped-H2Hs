import { Alert, Anchor, Button, Group, Loader, Stack, Table, Text } from "@mantine/core";
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { useCurrentEvent } from "../app/currentEvent";
import { setupLocked, setupPath } from "../app/guards";
import { useServices } from "../app/services";
import { EngineError } from "../engine/client";
import type { EventDocument, Pairings } from "../engine/types";
import { useBridgeQuery } from "../engine/useBridgeQuery";
import { drawSeed } from "./drawSeed";
import { SetupShell } from "./SetupShell";

/**
 * `#/e/:id/setup/3`: the pairings for every pass (UISpec.md 7.2 and 7.3, Stage 3), from the
 * bridge's `pairings`. "Redraw pairings" stores a new draw; "Confirm pairings and start event"
 * calls `start_event` and opens the current pass. Read-only once the event has started.
 *
 * @param props.doc - The event document.
 * @returns The view.
 */
export function Stage3({ doc }: { doc: EventDocument }) {
  const pairings = useBridgeQuery("pairings", { doc });
  return (
    <SetupShell doc={doc} stage={3}>
      {pairings.state === "loading" && <Loader aria-label="Loading the pairings" />}
      {pairings.state === "error" && (
        <Alert color="red" title="The pairings cannot load">
          {pairings.error.message}
        </Alert>
      )}
      {pairings.state === "ok" && <Stage3Body doc={doc} pairings={pairings.data} />}
    </SetupShell>
  );
}

/**
 * The pairings table and the Stage 3 actions.
 *
 * @param props.doc - The event document.
 * @param props.pairings - The bridge's pairings for the document's draw.
 * @returns The body.
 */
function Stage3Body({ doc, pairings }: { doc: EventDocument; pairings: Pairings }) {
  const { engine } = useServices();
  const { commit } = useCurrentEvent();
  const navigate = useNavigate();
  const [busy, setBusy] = useState<"redraw" | "start" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const locked = setupLocked(doc);

  async function run(action: "redraw" | "start") {
    setBusy(action);
    setError(null);
    try {
      const answer =
        action === "redraw"
          ? await engine.call("redraw", { doc, seed: drawSeed() })
          : await engine.call("start_event", { doc });
      if (!answer.ok) {
        setError(answer.error.message);
        return;
      }
      if (!(await commit(answer.data.document))) return;
      if (action === "start") navigate(`/e/${encodeURIComponent(doc.id)}/pass`);
    } catch (caught) {
      setError(caught instanceof EngineError ? caught.message : String(caught));
    } finally {
      setBusy(null);
    }
  }

  return (
    <Stack>
      <Text size="sm">
        {locked
          ? "The pairings for every pass, as drawn when the event started."
          : "Here are the pairings for every pass, drawn at random. Redraw as many times as you like, then confirm to start the event."}
      </Text>
      <div aria-live="polite">
        {error !== null && (
          <Alert color="red" data-testid="stage3-error">
            {error}
          </Alert>
        )}
      </div>
      <Table.ScrollContainer minWidth={360}>
        <Table data-testid="pairings-table" striped verticalSpacing="xs">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Pass</Table.Th>
              <Table.Th>Matches</Table.Th>
              <Table.Th>Sitting out</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {pairings.passes.map((pass) => (
              <Table.Tr key={pass.pass_number}>
                <Table.Td>{pass.pass_number}</Table.Td>
                <Table.Td>
                  {pass.matches.map((match, i) => (
                    <div key={i}>
                      {match.b === null
                        ? `${match.a} (bye - shoots alone)`
                        : `${match.a} vs ${match.b}`}
                    </div>
                  ))}
                </Table.Td>
                <Table.Td>
                  {pass.sitting_out.length > 0 ? pass.sitting_out.join(", ") : "-"}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
      <Group>
        <Anchor component={Link} to={setupPath(doc.id, 2)} size="sm">
          Back to Stage 2
        </Anchor>
        {!locked && (
          <>
            <Button
              variant="default"
              loading={busy === "redraw"}
              disabled={busy !== null}
              onClick={() => void run("redraw")}
            >
              Redraw pairings
            </Button>
            <Button
              loading={busy === "start"}
              disabled={busy !== null}
              onClick={() => void run("start")}
            >
              Confirm pairings and start event
            </Button>
          </>
        )}
      </Group>
    </Stack>
  );
}
