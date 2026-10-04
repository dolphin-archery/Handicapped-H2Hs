import { AppShell, Anchor, NavLink, ScrollArea, Text, Tooltip } from "@mantine/core";
import { Link, useLocation } from "react-router";
import { eventHomePath, setupPath } from "../app/guards";
import { useCurrentEvent } from "../app/currentEvent";
import type { EventDocument } from "../engine/types";

/**
 * How far the event's setup has got, for the navbar.
 *
 * @param doc - The event document.
 * @returns e.g. "Stage 1 of 3 done".
 */
function setupProgress(doc: EventDocument): string {
  if (doc.status !== "setup") return "Done";
  return doc.setup.stage === 0 ? "Not started" : `Stage ${doc.setup.stage} of 3 done`;
}

/**
 * A navbar link that may be disabled, with a tooltip saying why (UISpec.md 7.1).
 *
 * @param props.label - The link text.
 * @param props.to - The route.
 * @param props.active - Whether it is the current section.
 * @param props.description - Optional second line.
 * @param props.disabledReason - Why it cannot be used yet, or undefined if it can.
 * @param props.onNavigate - Called when followed (closes the phone drawer).
 * @returns The link.
 */
function Item({
  label,
  to,
  active,
  description,
  disabledReason,
  onNavigate,
}: {
  label: string;
  to: string;
  active: boolean;
  description?: string;
  disabledReason?: string;
  onNavigate: () => void;
}) {
  if (disabledReason !== undefined) {
    return (
      <Tooltip label={disabledReason} position="right" withArrow multiline w={220}>
        <div>
          <NavLink label={label} description={description} disabled aria-disabled="true" />
        </div>
      </Tooltip>
    );
  }
  return (
    <NavLink
      component={Link}
      to={to}
      label={label}
      description={description}
      active={active}
      onClick={onNavigate}
    />
  );
}

/**
 * The left navigation: Home; the current event's Setup, Current pass and Results; the handicap
 * calculator and About; and the privacy line (UISpec.md 7.1).
 *
 * @param props.onNavigate - Called when a link is followed.
 * @returns The navbar content.
 */
export function Navbar({ onNavigate }: { onNavigate: () => void }) {
  const { pathname } = useLocation();
  const { state } = useCurrentEvent();
  const doc = state.kind === "found" ? state.doc : null;
  const notStarted = "Available once the pairings are confirmed at Stage 3.";
  const base = doc === null ? "" : `/e/${encodeURIComponent(doc.id)}`;
  return (
    <>
      <AppShell.Section grow component={ScrollArea} p="xs">
        <nav aria-label="Main">
          <Item label="Home" to="/" active={pathname === "/"} onNavigate={onNavigate} />
          {doc !== null && (
            <>
              <Text
                size="xs"
                c="dimmed"
                fw={700}
                tt="uppercase"
                px="sm"
                pt="md"
                pb={4}
                truncate="end"
              >
                {doc.name}
              </Text>
              <Item
                label="Setup"
                description={setupProgress(doc)}
                to={doc.status === "setup" ? eventHomePath(doc) : setupPath(doc.id, 1)}
                active={pathname.startsWith(`${base}/setup`)}
                onNavigate={onNavigate}
              />
              <Item
                label="Current pass"
                to={`${base}/pass`}
                active={pathname.startsWith(`${base}/pass`)}
                disabledReason={doc.status === "setup" ? notStarted : undefined}
                onNavigate={onNavigate}
              />
              <Item
                label="Results"
                to={`${base}/results/leaderboard`}
                active={pathname.startsWith(`${base}/results`)}
                disabledReason={doc.status === "setup" ? notStarted : undefined}
                onNavigate={onNavigate}
              />
            </>
          )}
          <Text size="xs" c="dimmed" fw={700} tt="uppercase" px="sm" pt="md" pb={4}>
            Tools
          </Text>
          <Item
            label="Handicap calculator"
            to="/calculator"
            active={pathname === "/calculator"}
            onNavigate={onNavigate}
          />
          <Item label="About" to="/about" active={pathname === "/about"} onNavigate={onNavigate} />
        </nav>
      </AppShell.Section>
      <AppShell.Section p="md">
        <Text size="xs" c="dimmed">
          All data stays in this browser. Download a backup to keep it safe.{" "}
          <Anchor component={Link} to="/about" size="xs" onClick={onNavigate}>
            More
          </Anchor>
        </Text>
      </AppShell.Section>
    </>
  );
}
