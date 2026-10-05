import "@mantine/core/styles.css";
import "@mantine/notifications/styles.css";
import "./styles.css";

import { MantineProvider } from "@mantine/core";
import { ModalsProvider } from "@mantine/modals";
import { Notifications } from "@mantine/notifications";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { ServicesProvider } from "./app/services";
import { settingsColorSchemeManager, SettingsProvider } from "./app/settings";
import { getEngine } from "./engine/browserEngine";
import { getSettings } from "./storage/autosave";
import { EventStore } from "./storage/db";
import { cssVariablesResolver, theme } from "./theme";

const store = new EventStore();
const engine = getEngine();
// Python loads in the background from the start (UISpec.md 7.6); views stay usable meanwhile.
engine.start();

// Settings are read before the first render so the colour scheme does not flash (decision D8).
const settings = await getSettings(store);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <MantineProvider
      theme={theme}
      cssVariablesResolver={cssVariablesResolver}
      defaultColorScheme="auto"
      colorSchemeManager={settingsColorSchemeManager(store, settings.color_scheme)}
    >
      <ServicesProvider services={{ engine, store }}>
        <SettingsProvider store={store} initial={settings}>
          <ModalsProvider>
            <Notifications position="top-right" />
            <App />
          </ModalsProvider>
        </SettingsProvider>
      </ServicesProvider>
    </MantineProvider>
  </StrictMode>,
);
