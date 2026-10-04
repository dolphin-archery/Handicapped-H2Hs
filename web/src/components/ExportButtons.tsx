import { Button, Group } from "@mantine/core";
import { useState } from "react";
import { useServices } from "../app/services";
import type { EventDocument, ExportKind } from "../engine/types";
import { downloadExport, EXPORTS } from "./exports";

/**
 * The three export downloads as buttons, each with a loading state while it is built.
 *
 * @param props.doc - The event document.
 * @returns The buttons.
 */
export function ExportButtons({ doc }: { doc: EventDocument }) {
  const { engine } = useServices();
  const [busy, setBusy] = useState<ExportKind | null>(null);
  return (
    <Group gap="xs">
      {EXPORTS.map(({ kind, label }) => (
        <Button
          key={kind}
          size="xs"
          variant="default"
          loading={busy === kind}
          onClick={() => {
            setBusy(kind);
            void downloadExport(engine, doc, kind).finally(() => setBusy(null));
          }}
        >
          {label}
        </Button>
      ))}
    </Group>
  );
}
