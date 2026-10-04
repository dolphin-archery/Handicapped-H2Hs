/* eslint-disable react-refresh/only-export-components -- a context or action module exports its components and helpers together */
/**
 * Event actions shared by Home and the header: rename, delete (confirmed) and download a backup
 * (UISpec.md 7.1 header, 7.3 Home and "Delete event / reset", 6 rule 7).
 */
import { Button, Group, Text, TextInput } from "@mantine/core";
import { modals } from "@mantine/modals";
import { notifications } from "@mantine/notifications";
import { useState } from "react";
import { backupFileName, backupText, exportEvents } from "../storage/backup";
import type { EventStore } from "../storage/db";
import { downloadFile } from "../app/download";
import { nowIso } from "../app/services";

/**
 * The rename form shown in a modal.
 *
 * @param props.initial - The current name.
 * @param props.onSave - Called with the new, trimmed name.
 * @param props.onCancel - Called when the user cancels.
 * @returns The form.
 */
function RenameForm({
  initial,
  onSave,
  onCancel,
}: {
  initial: string;
  onSave: (name: string) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(initial);
  const trimmed = name.trim();
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        if (trimmed) onSave(trimmed);
      }}
    >
      <TextInput
        label="Event name"
        value={name}
        onChange={(event) => setName(event.currentTarget.value)}
        error={trimmed ? undefined : "Enter a name."}
        data-autofocus
      />
      <Group justify="flex-end" mt="md">
        <Button variant="default" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" disabled={!trimmed}>
          Save name
        </Button>
      </Group>
    </form>
  );
}

/**
 * Ask for a new event name.
 *
 * @param currentName - The name to start from.
 * @param onRename - Called with the new name once the user saves.
 */
export function openRenameModal(currentName: string, onRename: (name: string) => void): void {
  const id = modals.open({
    title: "Rename event",
    children: (
      <RenameForm
        initial={currentName}
        onCancel={() => modals.close(id)}
        onSave={(name) => {
          modals.close(id);
          onRename(name);
        }}
      />
    ),
  });
}

/**
 * Ask the user to confirm deleting an event, naming it (UISpec.md 7.3).
 *
 * @param name - The event's name.
 * @param onConfirm - Called if the user confirms.
 */
export function confirmDelete(name: string, onConfirm: () => void): void {
  modals.openConfirmModal({
    title: `Delete "${name}"?`,
    children: (
      <Text size="sm">
        This permanently deletes the event and all its scores from this browser. Download a backup
        first if you may need it again.
      </Text>
    ),
    labels: { confirm: "Delete event", cancel: "Keep it" },
    confirmProps: { color: "red" },
    onConfirm,
  });
}

/**
 * Download a backup of one stored event, or of a document held in memory.
 *
 * @param store - The event store.
 * @param event - The event id to export from storage, or a document (or raw value) to export as
 *   it is (used when storage has failed, or for a corrupt value).
 */
export async function downloadBackup(store: EventStore, event: string | unknown): Promise<void> {
  const now = nowIso();
  if (typeof event !== "string") {
    downloadFile(backupFileName(now), backupText([event], now), "application/json");
    return;
  }
  const result = await exportEvents(store, now, event);
  if (result.status === "ok") {
    downloadFile(result.filename, result.text, "application/json");
  } else {
    notifications.show({ color: "red", title: "Backup failed", message: result.failure.message });
  }
}
