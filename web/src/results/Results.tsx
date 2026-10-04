import {
  Accordion,
  Alert,
  Anchor,
  Button,
  Card,
  Group,
  Loader,
  Modal,
  Stack,
  Table,
  Tabs,
  Text,
  Title,
} from "@mantine/core";
import { useState } from "react";
import { Link, useNavigate } from "react-router";
import { RESULT_TABS, type ResultTab } from "../app/guards";
import { useSettings } from "../app/settings";
import { PairChartPanel } from "../chart/MatchChart";
import { DownloadMenu } from "../components/ExportButtons";
import { usePageTitle } from "../components/usePageTitle";
import type { ArcherResults, EventDocument, PairwiseRow, Results } from "../engine/types";
import { useBridgeQuery } from "../engine/useBridgeQuery";
import { PassTable } from "../scoring/PassTable";

const TAB_LABELS: Record<ResultTab, string> = {
  leaderboard: "Leaderboard",
  pairwise: "Pairwise",
  passes: "Passes",
  archers: "Archers",
};

/**
 * `#/e/:id/results/:tab` (UISpec.md 7.2 and 7.3, Results; decision D4): the event's results in
 * four tabs, from the bridge's `results` and `archer_results`. Every value is the bridge's text,
 * shown as it is.
 *
 * @param props.doc - The event document.
 * @param props.tab - The open tab (checked by the route guard).
 * @returns The view.
 */
export function ResultsView({ doc, tab }: { doc: EventDocument; tab: ResultTab }) {
  const results = useBridgeQuery("results", { doc }, true);
  const archers = useBridgeQuery("archer_results", { doc }, true);
  const navigate = useNavigate();
  const id = encodeURIComponent(doc.id);
  usePageTitle(`Results: ${TAB_LABELS[tab]}`);

  if (results.state === "loading" || archers.state === "loading") {
    return <Loader role="status" aria-label="Loading the results" />;
  }
  if (results.state === "error" || archers.state === "error") {
    const error =
      results.state === "error" ? results.error : archers.state === "error" ? archers.error : null;
    return (
      <Alert color="red" title="The results cannot load">
        {error?.message}
      </Alert>
    );
  }
  const data = results.data;

  return (
    <Stack>
      <Group justify="space-between" align="flex-start">
        <div>
          <Title order={1}>Event results</Title>
          {data.event_complete ? (
            <Text size="sm">Event complete.</Text>
          ) : (
            <Anchor component={Link} to={`/e/${id}/pass`} size="sm">
              Continue scoring (pass {data.current_pass_number} of {data.n_passes})
            </Anchor>
          )}
        </div>
        <DownloadMenu doc={doc} />
      </Group>
      <Tabs
        value={tab}
        onChange={(value) => value !== null && navigate(`/e/${id}/results/${value}`)}
        keepMounted={false}
      >
        <Tabs.List grow>
          {RESULT_TABS.map((value) => (
            <Tabs.Tab key={value} value={value}>
              {TAB_LABELS[value]}
            </Tabs.Tab>
          ))}
        </Tabs.List>
        <Tabs.Panel value="leaderboard" pt="md">
          <Leaderboard data={data} />
        </Tabs.Panel>
        <Tabs.Panel value="pairwise" pt="md">
          <Pairwise doc={doc} rows={data.pairwise} />
        </Tabs.Panel>
        <Tabs.Panel value="passes" pt="md">
          <Passes data={data} />
        </Tabs.Panel>
        <Tabs.Panel value="archers" pt="md">
          <Archers data={archers.data} />
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}

/**
 * The leaderboard tab (the Flask results page's first table and its explanation). Its Download
 * menu is the one in the view's header, shown once rather than twice.
 *
 * @param props.data - The bridge's `results`.
 * @returns The tab's content.
 */
function Leaderboard({ data }: { data: Results }) {
  return (
    <Stack gap="sm">
      <Text size="sm" data-testid="leaderboard-caption">
        1 point for each pass won, 0 for a pass lost. Only completed passes count (a pass is
        completed once every match in it has been scored): {data.completed_passes} of{" "}
        {data.n_passes} so far. Archers on equal points share a rank.
      </Text>
      <Table.ScrollContainer minWidth={320}>
        <Table data-testid="leaderboard-table" striped verticalSpacing="xs" horizontalSpacing="xs">
          <Table.Thead>
            <Table.Tr>
              <Table.Th>Rank</Table.Th>
              <Table.Th>Archer</Table.Th>
              <Table.Th>Points</Table.Th>
              <Table.Th>Passes decided</Table.Th>
              <Table.Th>Starting handicap</Table.Th>
              <Table.Th>To-date handicap</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {data.leaderboard.map((row) => (
              <Table.Tr key={row.archer_index}>
                <Table.Td>{row.rank}</Table.Td>
                <Table.Td>{row.name}</Table.Td>
                <Table.Td>{row.points}</Table.Td>
                <Table.Td>{row.passes_decided}</Table.Td>
                <Table.Td>{row.starting_handicap}</Table.Td>
                <Table.Td>{row.to_date_handicap}</Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      </Table.ScrollContainer>
    </Stack>
  );
}

/**
 * The pairwise tab: every pair who have shared a pass, with "View chart" (opening the pair chart
 * in a modal) when Graph view is on.
 *
 * @param props.doc - The event document.
 * @param props.rows - The bridge's pairwise rows.
 * @returns The tab's content.
 */
function Pairwise({ doc, rows }: { doc: EventDocument; rows: PairwiseRow[] }) {
  const { settings } = useSettings();
  const [open, setOpen] = useState<PairwiseRow | null>(null);
  return (
    <Stack gap="sm">
      <Text size="sm">
        Every pair of archers who have shared at least one rotation so far, as head-to-head results.
      </Text>
      {rows.length === 0 ? (
        <Text size="sm">No pairs have shared a rotation yet.</Text>
      ) : (
        <Table.ScrollContainer minWidth={320}>
          <Table data-testid="pairwise-table" striped verticalSpacing="xs" horizontalSpacing="xs">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>Archer A</Table.Th>
                <Table.Th>Archer B</Table.Th>
                <Table.Th>Wins A</Table.Th>
                <Table.Th>Wins B</Table.Th>
                <Table.Th>Result</Table.Th>
                {settings.graph_view && <Table.Th>Chart</Table.Th>}
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {rows.map((row) => (
                <Table.Tr key={`${row.archer_a}-${row.archer_b}`}>
                  <Table.Td>{row.name_a}</Table.Td>
                  <Table.Td>{row.name_b}</Table.Td>
                  <Table.Td>{row.wins_a}</Table.Td>
                  <Table.Td>{row.wins_b}</Table.Td>
                  <Table.Td>{row.result}</Table.Td>
                  {settings.graph_view && (
                    <Table.Td>
                      <Button
                        size="xs"
                        variant="default"
                        aria-label={`View chart: ${row.name_a} and ${row.name_b}`}
                        onClick={() => setOpen(row)}
                      >
                        View chart
                      </Button>
                    </Table.Td>
                  )}
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
        </Table.ScrollContainer>
      )}
      <Modal
        opened={open !== null}
        onClose={() => setOpen(null)}
        title={open ? `${open.name_a} and ${open.name_b}` : ""}
        size="xl"
      >
        {open && <PairChartPanel doc={doc} a={open.archer_a} b={open.archer_b} />}
      </Modal>
    </Stack>
  );
}

/**
 * The passes tab: one accordion item per pass in the bridge's `passes`, the latest open.
 *
 * @param props.data - The bridge's `results`.
 * @returns The tab's content.
 */
function Passes({ data }: { data: Results }) {
  if (data.passes.length === 0) return <Text size="sm">No pass has been scored yet.</Text>;
  const latest = String(data.passes[data.passes.length - 1].pass_index);
  return (
    <Accordion multiple defaultValue={[latest]} variant="separated" data-testid="passes">
      {data.passes.map((pass) => (
        <Accordion.Item key={pass.pass_index} value={String(pass.pass_index)}>
          <Accordion.Control>Pass {pass.pass_number}</Accordion.Control>
          <Accordion.Panel>
            <PassTable groups={pass.groups} showStartHandicap={data.show_start_handicap} />
          </Accordion.Panel>
        </Accordion.Item>
      ))}
    </Accordion>
  );
}

/**
 * The archers tab (the Flask archer results page): one card per archer with a heading line and
 * the passes table with its Average row.
 *
 * @param props.data - The bridge's `archer_results`.
 * @returns The tab's content.
 */
function Archers({ data }: { data: ArcherResults }) {
  const start = data.show_start_handicap;
  return (
    <Stack gap="sm">
      <Text size="sm">
        Each archer&apos;s results, counting only completed passes (a pass is completed once every
        match in it has been scored): {data.completed_passes} of {data.n_passes} so far.
      </Text>
      {data.completed_passes === 0 && (
        <Text size="sm" data-testid="no-completed-pass">
          No pass has been completed yet, so there are no results to show. They appear here once
          every match in a pass has been scored.
        </Text>
      )}
      {data.sections.map((section) => (
        <Card key={section.archer_index} withBorder padding="sm" data-testid="archer-section">
          <Title order={2} size="h4">
            {section.name}
          </Title>
          <Text size="sm" mb="xs" data-testid="archer-heading">
            Total score {section.total_score} - starting handicap {section.starting_handicap} -
            to-date handicap {section.to_date_handicap}
          </Text>
          {section.rows.length === 0 ? (
            <Text size="sm">No completed pass for {section.name} yet.</Text>
          ) : (
            <Table.ScrollContainer minWidth={300}>
              <Table verticalSpacing="xs" horizontalSpacing="xs">
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>Pass</Table.Th>
                    <Table.Th>Opponent</Table.Th>
                    <Table.Th>Score</Table.Th>
                    <Table.Th>Percentile</Table.Th>
                    {start && <Table.Th>Pass starting handicap</Table.Th>}
                    <Table.Th>Handicap</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {section.rows.map((row) => (
                    <Table.Tr key={row.pass_number}>
                      <Table.Td>{row.pass_number}</Table.Td>
                      <Table.Td>{row.opponent}</Table.Td>
                      <Table.Td>{row.score}</Table.Td>
                      <Table.Td>{row.percentile}</Table.Td>
                      {start && <Table.Td>{row.start_handicap}</Table.Td>}
                      <Table.Td>{row.handicap}</Table.Td>
                    </Table.Tr>
                  ))}
                  {section.average && (
                    <Table.Tr fw={700} data-testid="average-row">
                      <Table.Td colSpan={2}>Average</Table.Td>
                      <Table.Td>{section.average.score}</Table.Td>
                      <Table.Td>{section.average.percentile}</Table.Td>
                      {start && <Table.Td>{section.average.start_handicap}</Table.Td>}
                      <Table.Td>{section.average.handicap}</Table.Td>
                    </Table.Tr>
                  )}
                </Table.Tbody>
              </Table>
            </Table.ScrollContainer>
          )}
        </Card>
      ))}
    </Stack>
  );
}
