import { useEffect, useState, type ReactNode } from "react";

import { LatencyView } from "./components/LatencyView";
import { ServiceMap } from "./components/ServiceMap";
import { TraceList } from "./components/TraceList";
import { TraceView } from "./components/TraceView";
import { parseRoute, serviceMapHash, type Route } from "./route";

/** The application shell: a header and the screen selected by the URL hash. */
export function App() {
  const route = useRoute();
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
        {renderScreen(route)}
      </main>
    </div>
  );
}

/** The screen of a route. */
function renderScreen(route: Route): ReactNode {
  switch (route.screen) {
    case "list":
      return <TraceList />;
    case "trace":
      return <TraceView key={route.traceId} traceId={route.traceId} />;
    case "latency":
      return <LatencyView service={route.service} />;
    case "map":
      return <ServiceMap />;
  }
}

/** The current route, kept in step with the location hash. */
function useRoute(): Route {
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.hash));

  useEffect(() => {
    const onHashChange = () => {
      setRoute(parseRoute(window.location.hash));
    };
    window.addEventListener("hashchange", onHashChange);
    return () => {
      window.removeEventListener("hashchange", onHashChange);
    };
  }, []);

  return route;
}
