import { Paper, Stack, Title } from "@mantine/core";
import { CalculatorForm } from "../components/CalculatorForm";
import { usePageTitle } from "../components/usePageTitle";

/**
 * `#/calculator`: the standalone score-to-handicap calculator (UISpec.md 7.1, 7.3).
 *
 * @returns The view.
 */
export function Calculator() {
  usePageTitle("Handicap calculator");
  return (
    <Stack maw={560}>
      <Title order={1}>Handicap calculator</Title>
      <Paper withBorder p="md" radius="md">
        <CalculatorForm />
      </Paper>
    </Stack>
  );
}
