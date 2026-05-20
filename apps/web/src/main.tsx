import "maplibre-gl/dist/maplibre-gl.css";
import "./styles.css";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom";

import { MapPage } from "./pages/MapPage";
import { ParticipatePage } from "./pages/ParticipatePage";
import { RecordDetailPage } from "./pages/RecordDetailPage";
import { ReviewerPage } from "./pages/ReviewerPage";

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
          <Routes>
            <Route path="/" element={<MapPage />} />
            <Route path="/participate" element={<ParticipatePage />} />
            <Route path="/records/:publicId" element={<RecordDetailPage />} />
            <Route path="/review" element={<ReviewerPage />} />
          </Routes>
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
