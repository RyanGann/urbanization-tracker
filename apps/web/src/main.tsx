import "maplibre-gl/dist/maplibre-gl.css";
import "./styles.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { lazy, Suspense } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom";

const MapPage = lazy(() =>
  import("./pages/MapPage").then((module) => ({ default: module.MapPage }))
);
const ParticipatePage = lazy(() =>
  import("./pages/ParticipatePage").then((module) => ({ default: module.ParticipatePage }))
);
const RecordDetailPage = lazy(() =>
  import("./pages/RecordDetailPage").then((module) => ({ default: module.RecordDetailPage }))
);
const ReviewerPage = lazy(() =>
  import("./pages/ReviewerPage").then((module) => ({ default: module.ReviewerPage }))
);

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1
    }
  }
});

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <div className="app-shell">
          <header className="topbar">
            <NavLink className="brand" to="/" aria-label="Urbanization Tracker map">
              <span className="brand-mark">UT</span>
              <span>
                <strong>Urbanization Tracker</strong>
                <small>Huntsville pilot</small>
              </span>
            </NavLink>
            <nav className="topnav" aria-label="Primary">
              <NavLink to="/" end>
                Map
              </NavLink>
              <NavLink to="/participate">Participate</NavLink>
              <NavLink to="/review">Review</NavLink>
            </nav>
          </header>
          <Suspense
            fallback={
              <main className="page-shell route-loading" role="status">
                Loading page…
              </main>
            }
          >
            <Routes>
              <Route path="/" element={<MapPage />} />
              <Route path="/participate" element={<ParticipatePage />} />
              <Route path="/records/:publicId" element={<RecordDetailPage />} />
              <Route path="/review" element={<ReviewerPage />} />
            </Routes>
          </Suspense>
        </div>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
