import { HashRouter, Navigate, Route, Routes } from "react-router";
import { Shell } from "./components/Shell";
import { About } from "./routes/About";
import {
  EventIndex,
  EventLayout,
  MatchRoute,
  PassRoute,
  Placeholder,
  ResultsRoute,
  SetupRoute,
} from "./routes/EventRoutes";
import { Home } from "./routes/Home";

/**
 * The app's routes (UISpec.md 7.1), under a hash router (decision D2) so GitHub Pages never sees
 * a deep link. Unknown hashes go Home.
 *
 * @returns The router.
 */
export default function App() {
  return (
    <HashRouter>
      <Routes>
        <Route element={<Shell />}>
          <Route index element={<Home />} />
          <Route
            path="calculator"
            element={<Placeholder title="Handicap calculator" task="UI-10" />}
          />
          <Route path="about" element={<About />} />
          <Route path="e/:id" element={<EventLayout />}>
            <Route index element={<EventIndex />} />
            <Route path="setup/:stage" element={<SetupRoute />} />
            <Route path="pass" element={<PassRoute />} />
            <Route path="pass/match/:i" element={<MatchRoute />} />
            <Route path="results" element={<Navigate to="leaderboard" replace />} />
            <Route path="results/:tab" element={<ResultsRoute />} />
            <Route path="*" element={<EventIndex />} />
          </Route>
          <Route path="*" element={<Navigate to="/" replace />} />
        </Route>
      </Routes>
    </HashRouter>
  );
}
