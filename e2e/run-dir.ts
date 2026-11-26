import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

/** Environment variable that carries the run directory from the config to workers and teardown. */
const RUN_DIR_ENV = "TRACE_LENS_E2E_DIR";

/**
 * Returns the temporary directory of this e2e run, creating it on first use.
 *
 * The Playwright config is loaded by the runner and again by each worker, so the directory is
 * recorded in the environment: later loads reuse it instead of creating a second one. The
 * directory lives under the OS temporary directory, never inside the repository.
 */
export function runDirectory(): string {
  const existing = process.env[RUN_DIR_ENV];
  if (existing !== undefined) {
    return existing;
  }
  const directory = mkdtempSync(join(tmpdir(), "trace-lens-e2e-"));
  process.env[RUN_DIR_ENV] = directory;
  return directory;
}

/** Deletes the run directory, if this run created one, and forgets its location. */
export function removeRunDirectory(): void {
  const directory = process.env[RUN_DIR_ENV];
  if (directory === undefined) {
    return;
  }
  rmSync(directory, { recursive: true, force: true });
  delete process.env[RUN_DIR_ENV];
}
