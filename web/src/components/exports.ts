import { notifications } from "@mantine/notifications";
import { downloadFile } from "../app/download";
import type { EngineClient } from "../engine/client";
import { EngineError } from "../engine/client";
import type { EventDocument, ExportKind } from "../engine/types";

/** The three downloads and their labels (the Flask page's "Download:" links). */
export const EXPORTS: { kind: ExportKind; label: string }[] = [
  { kind: "leaderboard_csv", label: "Leaderboard (CSV)" },
  { kind: "archer_results_csv", label: "Archer results (CSV)" },
  { kind: "results_pdf", label: "Full report (PDF)" },
];

/**
 * The browser's local time as ISO-8601 without an offset, for `export`'s `now_iso` (the files
 * show local time; UISpec.md 5.4).
 *
 * @param now - The time (default: now).
 * @returns e.g. "2026-10-04T15:30:12".
 */
export function localIso(now: Date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}` +
    `T${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`
  );
}

/**
 * Build an export with the bridge and offer it as a download (deploymentConstrains 3, rule 5).
 * The first PDF waits while the engine installs the PDF library (decision D16).
 *
 * @param engine - The engine client.
 * @param doc - The event document.
 * @param kind - Which file.
 * @returns Resolves once the download is offered, or a red notification is shown.
 */
export async function downloadExport(
  engine: EngineClient,
  doc: EventDocument,
  kind: ExportKind,
): Promise<void> {
  try {
    const answer = await engine.call("export", { doc, kind, now_iso: localIso() });
    if (!answer.ok) {
      notifications.show({ color: "red", title: "Export failed", message: answer.error.message });
      return;
    }
    const file = answer.data;
    const content =
      file.encoding === "base64"
        ? Uint8Array.from(atob(file.content), (c) => c.charCodeAt(0))
        : file.content;
    downloadFile(file.filename, content, file.mime_type);
  } catch (error) {
    const message = error instanceof EngineError ? error.message : String(error);
    notifications.show({ color: "red", title: "Export failed", message });
  }
}
