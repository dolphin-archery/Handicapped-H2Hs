import { Container, Text, Title } from "@mantine/core";

/**
 * Placeholder page shown until the app shell (task UI-9) replaces it.
 * @returns The page content; main.tsx renders it inside MantineProvider.
 */
export default function App() {
  return (
    <Container component="main" size="md" py="xl">
      <Title order={1}>Handicapped H2Hs</Title>
      <Text mt="sm">The new web app is being built.</Text>
    </Container>
  );
}
