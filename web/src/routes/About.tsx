import { Anchor, List, Stack, Text, Title } from "@mantine/core";
import { usePageTitle } from "../components/usePageTitle";

/**
 * About: what the app does, where data is kept, and how to keep it safe (UISpec.md 7.1, 6 rule 7;
 * deploymentConstrains 3, rules 4 and 6).
 *
 * @returns The page.
 */
export function About() {
  usePageTitle("About");
  return (
    <Stack maw={760} gap="md">
      <Title order={1}>About Handicapped H2Hs</Title>
      <Text>
        Handicapped H2Hs runs fair head-to-head archery matches between archers of different skill
        levels and bowstyles. Each pass is won by the archer whose score is better for their own
        Archery GB handicap.
      </Text>

      <Title order={2} size="h3">
        Your data stays in this browser
      </Title>
      <List spacing="xs">
        <List.Item>
          Everything you enter is saved in this browser on this device, as you go. Nothing is sent
          to a server: the calculations run on your own device, and there are no accounts, analytics
          or tracking.
        </List.Item>
        <List.Item>
          Events do not move between devices or browsers, and private or incognito windows forget
          them when closed.
        </List.Item>
        <List.Item>
          Browsers can clear saved site data (for example after clearing browsing data, or Safari
          after a long time without a visit).
        </List.Item>
      </List>

      <Title order={2} size="h3">
        Keep a backup
      </Title>
      <Text>
        Use <strong>Download backup</strong> (on the Home page or in an event's menu) to save events
        to a file, especially when an event is complete. <strong>Import backup</strong> on the Home
        page brings them back, on this or another device.
      </Text>

      <Text size="sm" c="dimmed">
        The calculations use the{" "}
        <Anchor
          href="https://github.com/jatkinson1000/archeryutils"
          target="_blank"
          rel="noreferrer"
        >
          archeryutils
        </Anchor>{" "}
        implementation of the Archery GB handicap scheme, running in the browser with Pyodide.
      </Text>
    </Stack>
  );
}
