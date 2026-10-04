import { Anchor, createTheme, Drawer, Modal, type CSSVariablesResolver } from "@mantine/core";

/**
 * The app's Mantine theme. Overrides are for contrast (UISpec.md 7.5, WCAG AA 4.5:1 for text):
 * filled primary buttons and links use the darker blue shade 8, and links are underlined so they
 * are not told apart from text by colour alone; modal and drawer close buttons are named "Close". Animations are off when the system asks for reduced
 * motion.
 */
export const theme = createTheme({
  respectReducedMotion: true,
  primaryShade: { light: 8, dark: 8 },
  components: {
    Anchor: Anchor.extend({ defaultProps: { underline: "always" } }),
    Modal: Modal.extend({ defaultProps: { closeButtonProps: { "aria-label": "Close" } } }),
    Drawer: Drawer.extend({ defaultProps: { closeButtonProps: { "aria-label": "Close" } } }),
  },
});

/**
 * Text on light-variant badges, alerts and active links, for the light colour scheme: each colour's
 * shade 9 darkened until it has at least 5.5:1 contrast on its own shade 1 background (Mantine's
 * shade 9 is 3.8:1 for green and 2.7:1 for yellow).
 */
const LIGHT_VARIANT_TEXT: Record<string, string> = {
  teal: "#066b4d",
  green: "#20672e",
  blue: "#155a99",
  red: "#aa2323",
  yellow: "#954d00",
};

/**
 * Darker "dimmed" text than Mantine's default (gray 6 on white is about 3.3:1), so captions and
 * hints meet 4.5:1 in both colour schemes, and darker light-variant text in the light scheme.
 *
 * @returns The CSS variables per colour scheme.
 */
export const cssVariablesResolver: CSSVariablesResolver = () => ({
  variables: {},
  light: {
    "--mantine-color-dimmed": "var(--mantine-color-gray-7)",
    ...Object.fromEntries(
      Object.entries(LIGHT_VARIANT_TEXT).map(([color, hex]) => [
        `--mantine-color-${color}-light-color`,
        hex,
      ]),
    ),
  },
  dark: { "--mantine-color-dimmed": "var(--mantine-color-dark-1)" },
});
