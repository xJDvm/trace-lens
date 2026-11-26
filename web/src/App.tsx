import { useEffect, useState, type ReactNode } from "react";

import { LatencyView } from "./components/LatencyView";
import { TraceList } from "./components/TraceList";
import { TraceView } from "./components/TraceView";
import { parseRoute, type Route } from "./route";

/** The application shell: a header and the screen selected by the URL hash. */
export function App() {
  const route = useRoute();
  return (
    <div className="app">
      <header className="app-header">
        <h1>trace-lens</h1>
        <p className="tagline">Self-hosted OpenTelemetry traces</p>
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
