import { useEffect } from "react";

const APP_NAME = "Handicapped H2Hs";

/**
 * Set the page's <title> for the current view (UISpec.md 7.5).
 *
 * @param title - The view's name, e.g. "Stage 1"; empty for the app name alone.
 */
export function usePageTitle(title: string): void {
  useEffect(() => {
    document.title = title ? `${title} - ${APP_NAME}` : APP_NAME;
  }, [title]);
}
