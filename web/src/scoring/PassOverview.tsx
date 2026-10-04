import {
  Alert,
  Anchor,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Progress,
  Stack,
  Table,
  Text,
  Title,
  useMatches,
} from "@mantine/core";
import { modals } from "@mantine/modals";
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { useCurrentEvent } from "../app/currentEvent";
import { useServices } from "../app/services";
import { downloadBackup } from "../components/eventActions";
import { ExportButtons } from "../components/ExportButtons";
import { usePageTitle } from "../components/usePageTitle";
import { EngineError } from "../engine/client";
import type { EventDocument, Overview, OverviewMatch } from "../engine/types";
import { useBridgeQuery } from "../engine/useBridgeQuery";

/**
 * The Match column's text, as the Flask page wrote it.
 *
 * @param match - A match from `overview`.
 * @returns "Ann vs Ben", or "Ann (bye - no opponent, shoots alone)".
 */
function matchLabel(match: OverviewMatch): string {
  return match.bye
    ? `${match.names[0]} (bye - no opponent, shoots alone)`
    : match.names.join(" vs ");
}

/**
 * `#/e/:id/pass`: the current pass (UISpec.md 7.2 and 7.3, Current pass), from the bridge's
 * `overview`.
 *
 * @param props.doc - The event document.
 * @returns The view.
 */
export function PassOverview({ doc }: { doc: EventDocument }) {
  const overview = useBridgeQuery("overview", { doc });
  usePageTitle(overview.state === "ok" ? `Pass ${overview.data.pass_number}` : "Current pass");
  if (overview.state === "loading") return <Loader aria-label="Loading the pass" />;
  if (overview.state === "error") {
    return (
      <Alert color="red" title="The pass cannot load">
        {overview.error.message}
      </Alert>
    );
  }
  return <OverviewBody doc={doc} overview={overview.data} />;
}

/**
 * The overview once loaded: heading and progress, the match table, the sitting-out note, then
 * Advance (confirmed in a modal, decision D7) or, on the final pass, the completion alert.
 *
 * @param props.doc - The event document.
 * @param props.overview - The bridge's overview of the current pass.
 * @returns The body.
 */
function OverviewBody({ doc, overview }: { doc: EventDocument; overview: Overview }) {
  const { engine, store } = useServices();
  const { commit } = useCurrentEvent();
  const navigate = useNavigate();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const id = encodeURIComponent(doc.id);
  const matchPath = (index: number) => `/e/${id}/pass/match/${index}`;
  const complete = overview.is_last && doc.status === "complete";
  // Below `sm` the six columns do not fit, so each match is a card instead (UISpec.md 7.4).
  const cards = useMatches({ base: true, sm: false });

  async function advance() {
    setBusy(true);
    setError(null);
    try {
      const answer = await engine.call("advance", { doc });
      if (!answer.ok) setError(answer.error.message);
      else await commit(answer.data.document);
    } catch (caught) {
      setError(caught instanceof EngineError ? caught.message : String(caught));
    } finally {
      setBusy(false);
    }
  }

  function confirmAdvance() {
    modals.openConfirmModal({
      title: `Advance to pass ${overview.pass_number + 1}?`,
      children: (
        <Text size="sm">
          The scores of pass {overview.pass_number} can no longer be changed once the event moves
          on.
        </Text>
      ),
      labels: { confirm: "Advance", cancel: "Stay on this pass" },
      onConfirm: () => void advance(),
    });
  }

  return (
    <Stack>
      <div>
        <Title order={1}>
          Pass {overview.pass_number} of {overview.n_passes}
        </Title>
        <Text size="sm" c="dimmed">
          {overview.n_pass} arrows per pass. Open each match to enter its scores.
        </Text>
      </div>
      <div>
        <Text size="sm" mb={4} data-testid="scored-count">
          {overview.scored_count} of {overview.match_count} matches scored
        </Text>
        <Progress
          value={(100 * overview.scored_count) / Math.max(overview.match_count, 1)}
          aria-label="Matches scored"
        />
      </div>
      <div aria-live="polite">
        {error !== null && (
          <Alert color="red" data-testid="overview-error">
            {error}
          </Alert>
        )}
      </div>

      {cards ? (
        <Stack gap="xs" data-testid="overview-cards">
          {overview.matches.map((match) => (
            <Card key={match.index} withBorder padding="sm">
              <Group justify="space-between" wrap="nowrap" mb={4}>
                <Text fw={600} size="sm">
                  {matchLabel(match)}
                </Text>
                <Badge color={match.scored ? "teal" : "gray"} variant="light">
                  {match.scored ? "Scored" : "Not scored"}
                </Badge>
              </Group>
              <Text size="sm">Score: {match.score}</Text>
              <Text size="sm">Percentiles: {match.percentiles}</Text>
              <Text size="sm">Winner: {match.winner}</Text>
              <Button
                component={Link}
                to={matchPath(match.index)}
                mt="xs"
                variant={match.scored ? "default" : "filled"}
              >
                {match.scored ? "View / edit" : "Enter scores"}
              </Button>
            </Card>
          ))}
        </Stack>
      ) : (
        <Table.ScrollContainer minWidth={640}>
          <Table data-testid="overview-table" highlightOnHover verticalSpacing="sm">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Match</Table.Th>
                <Table.Th>Score</Table.Th>
                <Table.Th>Percentiles</Table.Th>
                <Table.Th>Winner</Table.Th>
                <Table.Th>Status</Table.Th>
                <Table.Th>Actions</Table.Th>
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {overview.matches.map((match) => (
                <Table.Tr
                  key={match.index}
                  onClick={() => navigate(matchPath(match.index))}
                  style={{ cursor: "pointer" }}
                >
                  <Table.Td>{matchLabel(match)}</Table.Td>
                  <Table.Td>{match.score}</Table.Td>
                  <Table.Td>{match.percentiles}</Table.Td>
                  <Table.Td>{match.winner}</Table.Td>
                  <Table.Td>
                    <Badge color={match.scored ? "teal" : "gray"} variant="light">
                      {match.scored ? "Scored" : "Not scored"}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    <Button
                      component={Link}
                      to={matchPath(match.index)}
                      size="xs"
                      variant={match.scored ? "default" : "filled"}
                      onClick={(event) => event.stopPropagation()}
                    >
                      {match.scored ? "View / edit" : "Enter scores"}
                    </Button>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}

      {overview.sitting_out.length > 0 && (
        <Text size="sm" data-testid="sitting-out">
          Sitting out this pass: {overview.sitting_out.join(", ")}.
        </Text>
      )}

      {complete ? (
        <Alert color="teal" title="The event is complete" data-testid="completion">
          <Stack gap="sm">
            <Text size="sm">Every pass has been scored.</Text>
            <Group>
              <Button component={Link} to={`/e/${id}/results/leaderboard`}>
                View results
              </Button>
            </Group>
            <ExportButtons doc={doc} />
            <Group gap="xs">
              <Button size="xs" variant="light" onClick={() => void downloadBackup(store, doc.id)}>
                Download backup
              </Button>
              <Text size="xs">
                This event is saved only in this browser. Download a backup to keep it safe.
              </Text>
            </Group>
          </Stack>
        </Alert>
      ) : overview.is_last ? (
        <Text size="sm">This is the final pass. Score every match to complete the event.</Text>
      ) : (
        <Group>
          <Button disabled={!overview.pass_complete} loading={busy} onClick={confirmAdvance}>
            Advance to next pass
          </Button>
          {!overview.pass_complete && (
            <Text size="sm" c="dimmed" data-testid="advance-hint">
              Enter scores for every match in this pass first.
            </Text>
          )}
        </Group>
      )}

      {!complete && (
        <Anchor component={Link} to={`/e/${id}/results/leaderboard`} size="sm">
          View results so far
        </Anchor>
      )}
    </Stack>
  );
}
