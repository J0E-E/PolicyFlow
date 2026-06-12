// Trivial sanity test proving the Vitest + jsdom harness is wired and runnable.
// It renders nothing and imports no component — the real <App> smoke test is
// Epic 5. Without at least one test file, `vitest run` exits non-zero. This file
// stays permanently as the frontend parallel to the backend's test_harness.py.
describe("frontend test harness", () => {
  it("harness is wired and runnable", () => {
    expect(true).toBe(true);
  });
});
