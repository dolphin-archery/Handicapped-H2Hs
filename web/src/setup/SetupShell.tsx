import { Alert, Box, Paper, Stepper, Title, useMatches } from "@mantine/core";
import type { ReactNode } from "react";
import { useNavigate } from "react-router";
import { setupLocked, setupPath } from "../app/guards";
import type { EventDocument } from "../engine/types";
import { usePageTitle } from "../components/usePageTitle";

const STEPS = [
  { label: "Event", description: "Stage 1" },
  { label: "Archers", description: "Stage 2" },
  { label: "Pairings", description: "Stage 3" },
] as const;

/**
 * The setup shell (UISpec.md 7.3): a `Stepper` across the top (Event, Archers, Pairings), then
 * the stage's content in a centred card. Steps already reachable can be clicked.
 *
 * @param props.doc - The event document.
 * @param props.stage - The stage shown (1, 2 or 3).
 * @param props.wide - Use the full content width (Stage 2) instead of about 760 px.
 * @param props.children - The stage's content.
 * @returns The shell.
 */
export function SetupShell({
  doc,
  stage,
  wide = false,
  children,
}: {
  doc: EventDocument;
  stage: 1 | 2 | 3;
  wide?: boolean;
  children: ReactNode;
}) {
  usePageTitle(`Stage ${stage}`);
  const navigate = useNavigate();
  const locked = setupLocked(doc);
  // Below `sm` the step descriptions are dropped so the three steps fit a phone's width.
  const compact = useMatches({ base: true, sm: false });
  // A step is reachable once the stage before it is done (the route guard's rule).
  const reachable = (index: number) => index <= doc.setup.stage;
  return (
    <Box maw={wide ? undefined : 760} mx={wide ? undefined : "auto"}>
      <Title order={1} mb="md">
        Stage {stage}
      </Title>
      <Stepper
        active={stage - 1}
        onStepClick={(index) => {
          if (reachable(index)) navigate(setupPath(doc.id, (index + 1) as 1 | 2 | 3));
        }}
        size="sm"
        mb="lg"
      >
        {STEPS.map((step, index) => (
          <Stepper.Step
            key={step.label}
            label={step.label}
            description={compact ? undefined : step.description}
            allowStepSelect={reachable(index) && index !== stage - 1}
          />
        ))}
      </Stepper>
      {locked && (
        <Alert color="blue" mb="md" data-testid="setup-locked">
          The event has started, so its setup can no longer be changed. This is a summary of what
          was entered.
        </Alert>
      )}
      <Paper withBorder radius="md" p={{ base: "sm", sm: "lg" }}>
        {children}
      </Paper>
    </Box>
  );
}
