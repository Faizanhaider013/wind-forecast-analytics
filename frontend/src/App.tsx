import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { DecisionPage } from "./pages/DecisionPage";
import { AccuracyPage } from "./pages/AccuracyPage";

const BrandMark = (
  <svg className="brand__mark" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path
      d="M4 14c3 0 3-3 6-3s3 3 6 3 3-3 4-3M4 19c3 0 3-3 6-3s3 3 6 3 3-3 4-3M12 11V4m0 0L9.5 6.5M12 4l2.5 2.5"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export default function App() {
  return (
    <>
      <header className="app-header">
        <div className="app-header__inner">
          <span className="brand">
            {BrandMark}
            UK Wind Forecast Decision Tool
          </span>
          <nav className="nav" aria-label="Primary">
            <NavLink to="/decision">Day-ahead decision</NavLink>
            <NavLink to="/accuracy">Forecast accuracy</NavLink>
          </nav>
        </div>
      </header>

      <Routes>
        <Route path="/" element={<Navigate to="/decision" replace />} />
        <Route path="/decision" element={<DecisionPage />} />
        <Route path="/accuracy" element={<AccuracyPage />} />
        <Route path="*" element={<Navigate to="/decision" replace />} />
      </Routes>
    </>
  );
}
