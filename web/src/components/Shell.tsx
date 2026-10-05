import { AppShell, Box } from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { Outlet } from "react-router";
import { CurrentEventProvider } from "../app/currentEvent";
import { useServices } from "../app/services";
import { EngineBanner } from "./EngineBanner";
import { Header } from "./Header";
import { Navbar } from "./Navbar";
import { StorageFailureAlert } from "./StorageFailureAlert";

/**
 * The application shell (UISpec.md 7.1): header, a left navbar that is always visible from the
 * `md` breakpoint and a burger-opened drawer below it, and the content area (at most about
 * 1200 px wide) with the engine banner and the storage-failure alert above the current view.
 *
 * @returns The layout route element.
 */
export function Shell() {
  const { engine } = useServices();
  const [navOpened, { toggle, close }] = useDisclosure(false);
  return (
    <CurrentEventProvider>
      <AppShell
        header={{ height: 56 }}
        navbar={{ width: 260, breakpoint: "md", collapsed: { mobile: !navOpened } }}
        padding="md"
      >
        <AppShell.Header>
          <Header navOpened={navOpened} onToggleNav={toggle} />
        </AppShell.Header>
        <AppShell.Navbar>
          <Navbar onNavigate={close} />
        </AppShell.Navbar>
        <AppShell.Main>
          <Box maw={1200} mx="auto">
            <EngineBanner engine={engine} />
            <StorageFailureAlert />
            <Outlet />
          </Box>
        </AppShell.Main>
      </AppShell>
    </CurrentEventProvider>
  );
}
