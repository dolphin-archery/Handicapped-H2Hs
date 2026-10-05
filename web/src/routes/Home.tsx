import {
  Alert,
  Badge,
  Button,
  Card,
  FileButton,
  Group,
  List,
  Loader,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { modals } from "@mantine/modals";
import { notifications } from "@mantine/notifications";
import { useCallback, useEffect, useState } from "react";
import { useNavigate } from "react-router";
import { useCurrentEvent } from "../app/currentEvent";
import { eventHomePath, setupPath } from "../app/guards";
import { nowIso, useServices } from "../app/services";
import { confirmDelete, downloadBackup, openRenameModal } from "../components/eventActions";
import { usePageTitle } from "../components/usePageTitle";
import { EngineError } from "../engine/client";
import type { Envelope, EventDocument } from "../engine/types";
import { getSessionRoute } from "../storage/autosave";
import { importBackup, storeImported } from "../storage/backup";
import type { IndexEntry } from "../storage/db";

/** One saved event as Home shows it: readable, or corrupt (with its raw value for export). */
type Item =
  | { kind: "ok"; entry: IndexEntry; doc: EventDocument }
  | { kind: "corrupt"; entry: IndexEntry; raw: unknown };

type ListState =
  { kind: "loading" } | { kind: "failed"; message: string } | { kind: "ready"; items: Item[] };

const STATUS_BADGE = {
  setup: { label: "Setting up", color: "gray" },
  running: { label: "In progress", color: "blue" },
  complete: { label: "Complete", color: "green" },
} as const;

/**
 * Where an event has got to, in words.
 *
 * @param doc - The event document.
 * @returns e.g. "Setup: stage 1 of 3 done", "Pass 3", "Complete".
 */
function progressText(doc: EventDocument): string {
  if (doc.status === "complete") return "Complete";
  if (doc.status === "running") return `Pass ${doc.current_pass + 1}`;
  return doc.setup.stage === 0 ? "Setup not started" : `Setup: stage ${doc.setup.stage} of 3 done`;
}

/**
 * A stored time as local date and time.
 *
 * @param iso - An ISO-8601 time.
 * @returns e.g. "4 Oct 2026, 15:30".
 */
function localTime(iso: string): string {
  return new Date(iso).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" });
}

/**
 * Home (UISpec.md 7.3): New event, Import backup, the Resume card for the most recently updated
 * in-progress event (decision D13), the saved events with Open, Rename, Download backup and
 * Delete, recovery for a stored value that cannot be read, and an empty state.
 *
 * @returns The page.
 */
export function Home() {
  usePageTitle("");
  const { engine, store } = useServices();
  const current = useCurrentEvent();
  const navigate = useNavigate();
  const [list, setList] = useState<ListState>({ kind: "loading" });
  const [creating, setCreating] = useState(false);
  const [importing, setImporting] = useState(false);

  const refresh = useCallback(async () => {
    const listed = await store.listEvents();
    if (listed.status === "failed") {
      setList({ kind: "failed", message: listed.failure.message });
      return;
    }
    const items: Item[] = [];
    for (const entry of listed.events) {
      const loaded = await store.loadEvent(entry.id);
      if (loaded.status === "found") items.push({ kind: "ok", entry, doc: loaded.document });
      if (loaded.status === "corrupt") items.push({ kind: "corrupt", entry, raw: loaded.raw });
    }
    setList({ kind: "ready", items });
  }, [store]);

  useEffect(() => {
    // refresh() sets state only after awaiting IndexedDB, never synchronously.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void refresh();
  }, [refresh]);

  const afterChange = () => {
    current.reload();
    void refresh();
  };

  async function open(doc: EventDocument) {
    const route = await getSessionRoute(store, doc.id);
    navigate(route ?? eventHomePath(doc));
  }

  async function createEvent() {
    setCreating(true);
    try {
      const made = await engine.call("new_document", {
        event_id: crypto.randomUUID(),
        now_iso: nowIso(),
      });
      if (!made.ok) {
        notifications.show({ color: "red", message: made.error.message });
        return;
      }
      const saved = await store.saveEvent(made.data, null, nowIso());
      if (saved.status === "saved") navigate(setupPath(saved.document.id, 1));
    } catch (error) {
      const message = error instanceof EngineError ? error.message : String(error);
      notifications.show({ color: "red", title: "Could not create the event", message });
    } finally {
      setCreating(false);
    }
  }

  async function rename(id: string, name: string) {
    const loaded = await store.loadEvent(id);
    if (loaded.status !== "found") return;
    const result = await store.renameEvent(id, name, loaded.document.revision, nowIso());
    if (result.status === "conflict") {
      notifications.show({ message: "That event was changed in another tab. Please try again." });
    }
    afterChange();
  }

  async function remove(entry: IndexEntry) {
    const result = await store.deleteEvent(entry.id);
    if (result.status === "deleted") notifications.show({ message: `Deleted "${entry.name}".` });
    else notifications.show({ color: "red", message: result.failure.message });
    afterChange();
  }

  async function importFile(file: File | null) {
    if (file === null) return;
    setImporting(true);
    const validate = (raw: unknown) =>
      engine.call("validate_document", { raw }) as Promise<Envelope<EventDocument>>;
    const result = await importBackup(store, file, validate, nowIso());
    setImporting(false);
    if (result.status === "rejected") {
      notifications.show({ color: "red", title: "Backup not imported", message: result.message });
      return;
    }
    for (const rejected of result.rejected) {
      notifications.show({
        color: "red",
        title: `Not imported: ${rejected.name ?? "an event"}`,
        message: rejected.message,
      });
    }
    if (result.imported.length > 0) {
      notifications.show({ message: `Imported ${result.imported.length} event(s).` });
    }
    if (result.needsConfirmation.length > 0) {
      const docs = result.needsConfirmation;
      modals.openConfirmModal({
        title: "Replace existing events?",
        children: (
          <Stack gap="xs">
            <Text size="sm">These events are already saved in this browser:</Text>
            <List size="sm">
              {docs.map((doc) => (
                <List.Item key={doc.id}>{doc.name}</List.Item>
              ))}
            </List>
            <Text size="sm">Replace them with the versions from the backup?</Text>
          </Stack>
        ),
        labels: { confirm: "Replace", cancel: "Keep the saved ones" },
        confirmProps: { color: "red" },
        onConfirm: () => {
          void storeImported(
            store,
            docs,
            nowIso(),
            docs.map((d) => d.id),
          ).then(afterChange);
        },
      });
    }
    afterChange();
  }

  const items = list.kind === "ready" ? list.items : [];
  const resume = items.find(
    (item): item is Extract<Item, { kind: "ok" }> =>
      item.kind === "ok" && item.doc.status !== "complete",
  );

  return (
    <Stack gap="lg">
      <Group justify="space-between" align="flex-end">
        <Title order={1}>Events</Title>
        <Group>
          <FileButton onChange={(file) => void importFile(file)} accept="application/json,.json">
            {(props) => (
              <Button variant="default" loading={importing} {...props}>
                Import backup
              </Button>
            )}
          </FileButton>
          <Button onClick={() => void createEvent()} loading={creating}>
            New event
          </Button>
        </Group>
      </Group>

      {resume !== undefined && (
        <Card withBorder padding="lg" data-testid="resume-card">
          <Text size="sm" c="dimmed">
            Resume event
          </Text>
          <Title order={2} size="h3">
            {resume.doc.name}
          </Title>
          <Text size="sm">{progressText(resume.doc)}</Text>
          <Group mt="md">
            <Button onClick={() => void open(resume.doc)}>Resume</Button>
            <Button variant="default" onClick={() => void createEvent()} loading={creating}>
              Start new event
            </Button>
          </Group>
        </Card>
      )}

      {list.kind === "loading" && <Loader role="status" aria-label="Loading saved events" />}
      {list.kind === "failed" && (
        <Alert color="red" title="Saved events cannot be read">
          {list.message}
        </Alert>
      )}
      {list.kind === "ready" && items.length === 0 && (
        <Text c="dimmed" maw={640}>
          Run fair head-to-head archery matches between archers of different skill levels, using
          their Archery GB handicaps. Start a new event to set up the archers and the pairings; it
          is saved in this browser as you go.
        </Text>
      )}

      {items.length > 0 && (
        <Stack gap="sm">
          <Title order={2} size="h4">
            Saved events
          </Title>
          <SimpleGrid cols={{ base: 1, sm: 2, lg: 3 }}>
            {items.map((item) =>
              item.kind === "ok" ? (
                <Card key={item.entry.id} withBorder data-testid="event-card">
                  <Group justify="space-between" wrap="nowrap" align="flex-start">
                    <Text fw={600} truncate="end">
                      {item.doc.name}
                    </Text>
                    <Badge color={STATUS_BADGE[item.doc.status].color} variant="light">
                      {STATUS_BADGE[item.doc.status].label}
                    </Badge>
                  </Group>
                  <Text size="sm" c="dimmed">
                    {item.doc.setup.n_archers} archers · {progressText(item.doc)}
                  </Text>
                  <Text size="sm" c="dimmed">
                    Last updated {localTime(item.doc.updated_at)}
                  </Text>
                  <Group gap="xs" mt="sm">
                    <Button size="xs" onClick={() => void open(item.doc)}>
                      Open
                    </Button>
                    <Button
                      size="xs"
                      variant="default"
                      onClick={() =>
                        openRenameModal(item.doc.name, (name) => void rename(item.doc.id, name))
                      }
                    >
                      Rename
                    </Button>
                    <Button
                      size="xs"
                      variant="default"
                      onClick={() => void downloadBackup(store, item.doc.id)}
                    >
                      Download backup
                    </Button>
                    <Button
                      size="xs"
                      variant="subtle"
                      color="red"
                      onClick={() => confirmDelete(item.doc.name, () => void remove(item.entry))}
                    >
                      Delete
                    </Button>
                  </Group>
                </Card>
              ) : (
                <Card key={item.entry.id} withBorder data-testid="corrupt-card">
                  <Text fw={600} c="red">
                    This saved event cannot be read
                  </Text>
                  <Text size="sm" c="dimmed">
                    {item.entry.name}. Download what can be read, then delete it.
                  </Text>
                  <Group gap="xs" mt="sm">
                    <Button
                      size="xs"
                      variant="default"
                      onClick={() => void downloadBackup(store, item.raw)}
                    >
                      Download what can be read
                    </Button>
                    <Button
                      size="xs"
                      variant="subtle"
                      color="red"
                      onClick={() => confirmDelete(item.entry.name, () => void remove(item.entry))}
                    >
                      Delete
                    </Button>
                  </Group>
                </Card>
              ),
            )}
          </SimpleGrid>
        </Stack>
      )}
    </Stack>
  );
}
