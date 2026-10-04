import { Alert, Button, Text } from "@mantine/core";
import { useSyncExternalStore } from "react";
import { useCurrentEvent } from "../app/currentEvent";
import { useServices } from "../app/services";
import { downloadBackup } from "./eventActions";

/**
 * The persistent "This event is NOT being saved" alert (UISpec.md 6, rule 1 and the failure
 * modes): shown while storage is failing, with a backup of the event as this tab holds it.
 *
 * @returns The alert, or nothing while storage works.
 */
export function StorageFailureAlert() {
  const { store } = useServices();
  const { state } = useCurrentEvent();
  const status = useSyncExternalStore(store.status.subscribe, store.status.getSnapshot);
  if (status.state !== "failed") return null;
  return (
    <Alert color="red" variant="filled" title="This event is NOT being saved" role="alert" mb="md">
      <Text size="sm">
        {status.message} Changes are kept in this tab only until it is closed. Download a backup now
        to keep them.
      </Text>
      {state.kind === "found" && (
        <Button
          mt="xs"
          size="xs"
          variant="white"
          color="red"
          onClick={() => void downloadBackup(store, state.doc)}
        >
          Download backup
        </Button>
      )}
    </Alert>
  );
}
