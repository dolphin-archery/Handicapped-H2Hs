import { Text } from "@mantine/core";
import { useSyncExternalStore } from "react";
import { useServices } from "../app/services";

/**
 * Local clock time HH:MM of an ISO timestamp.
 *
 * @param iso - An ISO-8601 time.
 * @returns e.g. "15:30".
 */
function clockTime(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" });
}

/**
 * The header's save indicator (UISpec.md 6, rule 3): "Saved HH:MM", "Saving..." or "Not saved".
 * Announced politely to screen readers.
 *
 * @returns The indicator, or nothing before the first save of the session.
 */
export function SaveIndicator() {
  const { store } = useServices();
  const status = useSyncExternalStore(store.status.subscribe, store.status.getSnapshot);
  let text = "";
  let color = "dimmed";
  if (status.state === "saving") text = "Saving...";
  if (status.state === "saved") text = `Saved ${clockTime(status.savedAt)}`;
  if (status.state === "failed") {
    text = "Not saved";
    color = "red";
  }
  return (
    <Text size="sm" c={color} aria-live="polite" data-testid="save-indicator" miw={0}>
      {text}
    </Text>
  );
}
