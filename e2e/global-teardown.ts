import { removeRunDirectory } from "./run-dir";

/** Removes the temporary database directory after all tests and servers of the run. */
export default function globalTeardown(): void {
  removeRunDirectory();
}
