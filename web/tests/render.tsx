import { MantineProvider } from "@mantine/core";
import { render as testingLibraryRender } from "@testing-library/react";
import type { ReactNode } from "react";
import { theme } from "../src/theme";

/**
 * Render UI inside the app's MantineProvider in test mode (no transitions or portals), as
 * Mantine's testing guide recommends.
 * @param ui The React node to render.
 * @returns Testing Library's render result (container, rerender, unmount and queries).
 */
export function render(ui: ReactNode) {
  return testingLibraryRender(ui, {
    wrapper: ({ children }: { children: ReactNode }) => (
      <MantineProvider theme={theme} env="test">
        {children}
      </MantineProvider>
    ),
  });
}
