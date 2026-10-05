import { Anchor, Burger, Button, Group, Menu, Switch, Text } from "@mantine/core";
import { notifications } from "@mantine/notifications";
import { Link, useNavigate } from "react-router";
import { useCurrentEvent } from "../app/currentEvent";
import { useServices } from "../app/services";
import { useSettings } from "../app/settings";
import { ColorSchemeMenu } from "./ColorSchemeMenu";
import { confirmDelete, downloadBackup, openRenameModal } from "./eventActions";
import { DotsIcon } from "./icons";
import { SaveIndicator } from "./SaveIndicator";

/**
 * The open event's name with its menu: Rename, Download backup, Delete event (UISpec.md 7.1).
 *
 * @returns The menu, or nothing outside an event.
 */
function EventMenu() {
  const { store } = useServices();
  const { state, routeId, rename, remove } = useCurrentEvent();
  const navigate = useNavigate();
  if (routeId === null || state.kind !== "found") return null;
  const doc = state.doc;
  return (
    <Menu position="bottom-start" withinPortal>
      <Menu.Target>
        <Button
          variant="subtle"
          color="gray"
          rightSection={<DotsIcon />}
          maw={{ base: 170, sm: 360 }}
          aria-label={`Event: ${doc.name}. Event menu`}
          data-testid="header-event-name"
        >
          <Text truncate="end" fw={600} size="sm">
            {doc.name}
          </Text>
        </Button>
      </Menu.Target>
      <Menu.Dropdown>
        <Menu.Item onClick={() => openRenameModal(doc.name, (name) => void rename(name))}>
          Rename
        </Menu.Item>
        <Menu.Item onClick={() => void downloadBackup(store, doc.id)}>Download backup</Menu.Item>
        <Menu.Divider />
        <Menu.Item
          color="red"
          onClick={() =>
            confirmDelete(doc.name, () => {
              void remove().then((deleted) => {
                if (!deleted) return;
                notifications.show({ message: `Deleted "${doc.name}".` });
                navigate("/");
              });
            })
          }
        >
          Delete event
        </Menu.Item>
      </Menu.Dropdown>
    </Menu>
  );
}

/**
 * The Graph view switch (decision D5: a device setting), shown while an event is running.
 *
 * @returns The switch, or nothing.
 */
function GraphViewSwitch() {
  const { state, routeId } = useCurrentEvent();
  const { settings, update } = useSettings();
  if (routeId === null || state.kind !== "found" || state.doc.status === "setup") return null;
  return (
    <Switch
      label="Graph view"
      checked={settings.graph_view}
      onChange={(event) => update({ graph_view: event.currentTarget.checked })}
      size="sm"
      styles={{ label: { whiteSpace: "nowrap" } }}
    />
  );
}

/**
 * The slim header: menu button (phones), app title, event menu, save indicator, Graph view switch
 * and colour scheme (UISpec.md 7.1).
 *
 * @param props.navOpened - Whether the phone navigation drawer is open.
 * @param props.onToggleNav - Opens or closes it.
 * @returns The header content.
 */
export function Header({
  navOpened,
  onToggleNav,
}: {
  navOpened: boolean;
  onToggleNav: () => void;
}) {
  const { routeId } = useCurrentEvent();
  return (
    <Group h="100%" px="md" justify="space-between" wrap="nowrap" gap="xs">
      <Group gap="xs" wrap="nowrap" miw={0}>
        <Burger
          opened={navOpened}
          onClick={onToggleNav}
          hiddenFrom="md"
          size="sm"
          aria-label={navOpened ? "Close navigation" : "Open navigation"}
        />
        <Anchor
          component={Link}
          to="/"
          fw={700}
          c="var(--mantine-color-text)"
          underline="never"
          visibleFrom={routeId === null ? undefined : "sm"}
        >
          Handicapped H2Hs
        </Anchor>
        <EventMenu />
      </Group>
      <Group gap="sm" wrap="nowrap">
        <SaveIndicator />
        <GraphViewSwitch />
        <ColorSchemeMenu />
      </Group>
    </Group>
  );
}
