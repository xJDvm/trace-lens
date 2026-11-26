import { TraceList } from "./components/TraceList";

/** The application shell: a header and the trace list. */
export function App() {
  return (
    <div className="app">
      <header className="app-header">
        <h1>trace-lens</h1>
        <p className="tagline">Self-hosted OpenTelemetry traces</p>
      </header>
      <main>
        <TraceList />
      </main>
    </div>
  );
}
