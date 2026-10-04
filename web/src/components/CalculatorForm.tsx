import {
  Alert,
  Button,
  Checkbox,
  Drawer,
  Loader,
  NumberInput,
  SegmentedControl,
  Select,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { useState, type FormEvent } from "react";
import { useServices } from "../app/services";
import { EngineError } from "../engine/client";
import type { CalculatorKind, Options } from "../engine/types";
import { useBridgeQuery } from "../engine/useBridgeQuery";

const KIND_LABELS: Record<CalculatorKind, string> = { indoor: "Indoor", outdoor: "Outdoor" };

/**
 * The score-to-handicap calculator (UISpec.md 7.2 and 7.3, Calculator): round type, round,
 * compound (indoor only), score in, handicap out. The round lists and the handicap come from the
 * bridge (`options` and `calculator`); nothing is stored.
 *
 * @returns The form, a loader while the engine starts, or the engine's error.
 */
export function CalculatorForm() {
  const options = useBridgeQuery("options", {});
  if (options.state === "loading") return <Loader aria-label="Loading the round lists" />;
  if (options.state === "error") {
    return (
      <Alert color="red" title="The calculator cannot load">
        {options.error.message}
      </Alert>
    );
  }
  return <CalculatorFields calculator={options.data.calculator} />;
}

/**
 * The calculator's fields once the round lists are known.
 *
 * @param props.calculator - `options().calculator`: kinds, rounds per kind and default rounds.
 * @returns The form.
 */
function CalculatorFields({ calculator }: { calculator: Options["calculator"] }) {
  const { engine } = useServices();
  const [kind, setKind] = useState<CalculatorKind>(calculator.kinds[0]);
  // One remembered round per kind, as the old page had one list per kind.
  const [rounds, setRounds] = useState<Record<CalculatorKind, string>>(calculator.defaults);
  const [compound, setCompound] = useState(false);
  const [score, setScore] = useState<string | number>("");
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<{ text: string } | { error: string } | null>(null);

  async function calculate(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    try {
      const answer = await engine.call("calculator", {
        kind,
        round_codename: rounds[kind],
        compound: kind === "indoor" && compound,
        score,
      });
      setOutcome(answer.ok ? { text: answer.data.text } : { error: answer.error.message });
    } catch (error) {
      setOutcome({ error: error instanceof EngineError ? error.message : String(error) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={(event) => void calculate(event)}>
      <Stack>
        <Text size="sm" c="dimmed">
          A convenience tool for working out a starting handicap. This result is not stored against
          any archer.
        </Text>
        <div>
          <Text size="sm" fw={500} mb={4} id="calculator-kind-label">
            Round type
          </Text>
          <SegmentedControl
            aria-labelledby="calculator-kind-label"
            value={kind}
            onChange={(value) => setKind(value as CalculatorKind)}
            data={calculator.kinds.map((k) => ({ value: k, label: KIND_LABELS[k] }))}
          />
        </div>
        <Select
          label="Round"
          searchable
          allowDeselect={false}
          nothingFoundMessage="No round matches"
          data={calculator.rounds[kind]}
          value={rounds[kind]}
          onChange={(value) => value !== null && setRounds({ ...rounds, [kind]: value })}
        />
        {kind === "indoor" && (
          <Checkbox
            label="Shot with a compound bow"
            description="Compound scores differently indoors: only the inner ring counts as 10."
            checked={compound}
            onChange={(event) => setCompound(event.currentTarget.checked)}
          />
        )}
        <NumberInput
          label="Full round score"
          inputMode="numeric"
          allowDecimal={false}
          allowNegative={false}
          hideControls
          value={score}
          onChange={setScore}
        />
        <Button type="submit" loading={busy} style={{ alignSelf: "flex-start" }}>
          Calculate
        </Button>
        <div aria-live="polite">
          {outcome !== null && "text" in outcome && (
            <Title order={2} size="h3" data-testid="calculator-result">
              Handicap: {outcome.text}
            </Title>
          )}
          {outcome !== null && "error" in outcome && (
            <Alert color="red" data-testid="calculator-error">
              {outcome.error}
            </Alert>
          )}
        </div>
      </Stack>
    </form>
  );
}

/**
 * The calculator in a drawer, so Stage 2 can use it without leaving the archers form (D6).
 *
 * @param props.opened - Whether the drawer is open.
 * @param props.onClose - Closes it.
 * @returns The drawer.
 */
export function CalculatorDrawer({ opened, onClose }: { opened: boolean; onClose: () => void }) {
  return (
    <Drawer
      opened={opened}
      onClose={onClose}
      title="Handicap calculator"
      position="right"
      size="md"
      keepMounted
    >
      <CalculatorForm />
    </Drawer>
  );
}
