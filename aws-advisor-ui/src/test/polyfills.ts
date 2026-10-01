// Browser APIs cmdk's Dialog (Radix) relies on that jsdom doesn't implement.
// Imported by vitest.setup.ts so the whole test suite gets them.

// Radix uses animate() for dialog open/close transitions.
if (typeof Element !== "undefined" && !Element.prototype.animate) {
  Element.prototype.animate = (() => null) as unknown as typeof Element.prototype.animate;
  Element.prototype.getAnimations = () => [];
}

// Radix's dismissable-layer / presence helpers observe size changes.
if (typeof globalThis !== "undefined" && typeof (globalThis as { ResizeObserver?: unknown }).ResizeObserver === "undefined") {
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  (globalThis as { ResizeObserver: unknown }).ResizeObserver = ResizeObserverStub;
}

// cmdk calls scrollIntoView on the selected item; jsdom has no layout engine.
if (typeof Element !== "undefined" && !Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}
