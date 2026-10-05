// Vitest setup, following Mantine's testing guide (https://mantine.dev/guides/vitest/).
// The browser mocks apply to jsdom tests only; files marked `@vitest-environment node` have no window.
import "@testing-library/jest-dom/vitest";
import { vi } from "vitest";

if (typeof window !== "undefined") {
  const { getComputedStyle } = window;
  window.getComputedStyle = (elt) => getComputedStyle(elt);
  window.HTMLElement.prototype.scrollIntoView = () => {};

  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });

  if (!document.fonts) {
    Object.defineProperty(document, "fonts", {
      writable: true,
      value: { addEventListener: vi.fn(), removeEventListener: vi.fn() },
    });
  }

  class ResizeObserver {
    observe() {}
    unobserve() {}
    disconnect() {}
  }

  window.ResizeObserver = ResizeObserver;
}
