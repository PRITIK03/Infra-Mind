import "@testing-library/jest-dom/vitest";

// Ensure the API module always sees a configured base URL in tests.
// NEXT_PUBLIC_API_URL is a compile-time constant in production but
// process.env is evaluated at module load in the test environment.
process.env.NEXT_PUBLIC_API_URL = "http://localhost:8000";

Object.defineProperty(window, "matchMedia", {
  writable: true,
  value: (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }),
});
