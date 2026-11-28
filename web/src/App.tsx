import { useEffect, useRef, useState, type ReactNode } from "react";

import { LatencyView } from "./components/LatencyView";
import { ServiceMap } from "./components/ServiceMap";
import { TraceList } from "./components/TraceList";
import { TraceView } from "./components/TraceView";
import { parseRoute, resumeListHash, serviceMapHash, type Route } from "./route";

/** The application shell: a header and the screen selected by the URL hash. */
export function App() {
  const hash = useHash();
  const route = parseRoute(hash);
  return (
    <div className="app">
      <header className="app-header">
        <h1>trace-lens</h1>
        <p className="tagline">Self-hosted OpenTelemetry traces</p>
        <nav className="app-nav" aria-label="Main">
          <a href="#/" aria-current={route.screen === "list" ? "page" : undefined}>
            Traces
          </a>
          <a href={serviceMapHash()} aria-current={route.screen === "map" ? "page" : undefined}>
            Service map
          </a>
        </nav>
      </header>
      <main>
        {renderScreen(route, hash)}
      </main>
    </div>
  );
}

/** The screen of a route. The list is keyed by the hash, so each list hash shows its filters. */
function renderScreen(route: Route, hash: string): ReactNode {
  switch (route.screen) {
    case "list":
      return <TraceList key={hash} />;
    case "trace":
      return <TraceView key={route.traceId} traceId={route.traceId} />;
    case "latency":
      return <LatencyView service={route.service} />;
    case "map":
      return <ServiceMap />;
  }
}

/**
 * The location hash, kept in step with the browser.
 *
 * The list hash that the user last left is remembered, so that a link back to the bare `#/`
 * (such as the back link of a trace) restores the list filters. The list reads its filters from
 * the hash when it is shown, so it is keyed by the hash and shows what the URL says.
 */
function useHash(): string {
  const [hash, setHash] = useState(() => window.location.hash);
  const lastListHash = useRef("#/");

  useEffect(() => {
    const onHashChange = (event: HashChangeEvent) => {
      // The list keeps its filters in the URL with `replaceState`, so the URL left behind is
      // the one to remember, not the hash this app last rendered.
      const previous = new URL(event.oldURL).hash || "#/";
      if (parseRoute(previous).screen === "list") {
        lastListHash.current = previous;
      } else {
        const resumed = resumeListHash(window.location.hash, lastListHash.current);
        if (resumed !== null) {
          window.history.replaceState(null, "", resumed);
        }
      }
      setHash(window.location.hash);
    };
    window.addEventListener("hashchange", onHashChange);
    return () => {
      window.removeEventListener("hashchange", onHashChange);
    };
  }, []);

  return hash;
}
