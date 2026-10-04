import {
  Alert,
  Anchor,
  Button,
  Grid,
  Group,
  Loader,
  NumberInput,
  Paper,
  Radio,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { useState, type FormEvent } from "react";
import { Link } from "react-router";
import { useCurrentEvent } from "../app/currentEvent";
import { useServices } from "../app/services";
import { useSettings } from "../app/settings";
import { useFormDraft, type FormDraft } from "../app/useFormDraft";
import { usePageTitle } from "../components/usePageTitle";
import { EngineError } from "../engine/client";
import type { EventDocument, MatchView } from "../engine/types";
import { useBridgeQuery } from "../engine/useBridgeQuery";
import { PairChartPanel } from "../chart/MatchChart";
import { PassTable } from "./PassTable";

/** The match form's values as typed (also its draft). */
export interface MatchDraft {
  /** Schedule position (as text) -> the score box's value. */
  scores: Record<string, string | number>;
  /** The position chosen as closest to the middle, or null. */
  closest: number | null;
  /** Whether the tie-break control is on screen (a refused tie, or a saved tie-break). */
  tiebreak: boolean;
}

/**
 * `#/e/:id/pass/match/:i`: score one match of the current pass (UISpec.md 7.2 and 7.3, Match),
 * from the bridge's `match`; saving calls `record_match`, stores the document, then shows it.
 *
 * @param props.doc - The event document.
 * @param props.index - The match's index in the current pass.
 * @returns The view.
 */
export function MatchPage({ doc, index }: { doc: EventDocument; index: number }) {
  const view = useBridgeQuery("match", { doc, match_index: index }, true);
  const draft = useFormDraft<MatchDraft>(doc.id, `match:${doc.current_pass}:${index}`);
  usePageTitle(`Match ${index + 1}`);
  const overview = `/e/${encodeURIComponent(doc.id)}/pass`;
  if (view.state === "error") {
    return (
      <Alert color="red" title="This match cannot be opened">
        <Text size="sm">{view.error.message}</Text>
        <Anchor component={Link} to={overview} size="sm" c="inherit">
          Back to overview
        </Anchor>
      </Alert>
    );
  }
  // A kept answer from before a save is fine; one for another match (after "Next unscored
  // match") is not, since the form would show and save the wrong match.
  if (view.state === "loading" || view.data.match_index !== index || !draft.loaded) {
    return <Loader role="status" aria-label="Loading the match" />;
  }
  return <MatchBody key={index} doc={doc} view={view.data} draft={draft} />;
}

/**
 * The match form and its results once loaded.
 *
 * @param props.doc - The event document.
 * @param props.view - The bridge's match view (as stored, before this form's changes).
 * @param props.draft - The form's draft.
 * @returns The body.
 */
function MatchBody({
  doc,
  view: stored,
  draft,
}: {
  doc: EventDocument;
  view: MatchView;
  draft: FormDraft<MatchDraft>;
}) {
  const { engine } = useServices();
  const { commit } = useCurrentEvent();
  const { settings } = useSettings();
  const [view, setView] = useState(stored);
  const [values, setValues] = useState<MatchDraft>(
    () =>
      draft.draft ?? {
        scores: Object.fromEntries(stored.archers.map((a) => [String(a.position), a.score ?? ""])),
        closest: stored.decided_by_closest ? stored.closest : null,
        tiebreak: stored.decided_by_closest,
      },
  );
  const [error, setError] = useState<{ code: string; message: string } | null>(null);
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);
  const id = encodeURIComponent(doc.id);
  const overview = `/e/${id}/pass`;
  const [a, b] = view.archers;

  function change(next: Partial<MatchDraft>) {
    const merged = { ...values, ...next };
    setValues(merged);
    setSaved(false);
    draft.save(merged);
  }

  async function save(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const answer = await engine.call("record_match", {
        doc,
        match_index: view.match_index,
        scores: values.scores,
        closest: values.tiebreak ? values.closest : null,
      });
      if (!answer.ok) {
        setError(answer.error);
        // A tie keeps the typed scores and asks who was closest to the middle.
        if (answer.error.code === "tiebreak_required") change({ tiebreak: true });
        return;
      }
      if (!(await commit(answer.data.document))) return;
      await draft.discard();
      const next = answer.data.match;
      setView(next);
      setValues({
        scores: values.scores,
        closest: next.decided_by_closest ? next.closest : null,
        tiebreak: next.decided_by_closest,
      });
      setSaved(true);
    } catch (caught) {
      setError({
        code: "internal",
        message: caught instanceof EngineError ? caught.message : String(caught),
      });
    } finally {
      setBusy(false);
    }
  }

  const form = (
    <Paper withBorder radius="md" p="md">
      <form onSubmit={(event) => void save(event)}>
        <Stack>
          {view.archers.map((archer, i) => (
            <NumberInput
              key={archer.position}
              label={`${archer.name} score (0-${archer.max_score})`}
              inputMode="numeric"
              hideControls
              clampBehavior="none"
              data-autofocus={i === 0 || undefined}
              autoFocus={i === 0}
              value={values.scores[String(archer.position)] ?? ""}
              onChange={(value) =>
                change({ scores: { ...values.scores, [String(archer.position)]: value } })
              }
            />
          ))}
          {!view.bye && values.tiebreak && b !== undefined && (
            <Radio.Group
              label="Tie-break: closest to the middle"
              description="The percentile and the score are tied, so the pass is decided by whose arrow was closest to the middle of the target. Choose that one archer: they win the pass."
              value={values.closest === null ? null : String(values.closest)}
              onChange={(value) => change({ closest: Number(value) })}
              data-testid="tiebreak"
            >
              <Group mt="xs">
                <Radio value={String(a.position)} label={a.name} />
                <Radio value={String(b.position)} label={b.name} />
              </Group>
            </Radio.Group>
          )}
          <div aria-live="polite">
            {error !== null && (
              <Alert
                color={error.code === "tiebreak_required" ? "yellow" : "red"}
                data-testid="match-error"
              >
                {error.message}
              </Alert>
            )}
            {saved && (
              <Alert color="teal" data-testid="match-saved">
                Scores saved.
              </Alert>
            )}
          </div>
          <Group>
            <Button type="submit" loading={busy}>
              {view.scored ? "Save changed scores" : "Save scores"}
            </Button>
            {saved && view.next_unscored_match !== null && (
              <Button
                component={Link}
                to={`${overview}/match/${view.next_unscored_match}`}
                variant="default"
              >
                Next unscored match
              </Button>
            )}
            {saved && (
              <Button component={Link} to={overview} variant="default">
                Back to overview
              </Button>
            )}
          </Group>
          {view.scored && (
            <Text size="xs" c="dimmed">
              Saving again replaces the scores below, until the event advances to the next pass.
            </Text>
          )}
        </Stack>
      </form>
    </Paper>
  );

  const results = view.scored && (
    <Stack gap="xs">
      <Title order={2} size="h3">
        This pass
      </Title>
      <PassTable groups={[view.rows]} showStartHandicap={view.show_start_handicap} />
      {view.decided_by_closest && (
        <Text size="xs" c="dimmed">
          Percentile and score were tied; decided by closest to the middle.
        </Text>
      )}
    </Stack>
  );

  return (
    <Stack>
      <div>
        <Title order={1}>
          {view.bye ? `${a.name} - bye, no opponent` : `${a.name} vs ${b.name}`}
        </Title>
        <Text size="sm" c="dimmed">
          Pass {view.pass_number} of {view.n_passes} ·{" "}
          <Anchor component={Link} to={overview} size="sm">
            Back to overview
          </Anchor>
        </Text>
      </div>
      {view.bye ? (
        <Stack maw={560}>
          {form}
          {results}
          <Text size="sm" c="dimmed">
            A bye match has no opponent to compare against, so there is no winner and no chart.
          </Text>
        </Stack>
      ) : (
        <Grid gap="lg">
          <Grid.Col span={{ base: 12, md: 6 }}>
            <Stack>
              {form}
              {results}
            </Stack>
          </Grid.Col>
          <Grid.Col span={{ base: 12, md: 6 }} data-testid="chart-column">
            {settings.graph_view ? (
              <Paper withBorder radius="md" p="md">
                <PairChartPanel doc={doc} a={a.position} b={b.position} />
              </Paper>
            ) : (
              <Text size="sm" c="dimmed" data-testid="graph-view-off">
                Graph view is off. Turn it on in the header to compare the two archers&apos; score
                distributions.
              </Text>
            )}
          </Grid.Col>
        </Grid>
      )}
    </Stack>
  );
}
