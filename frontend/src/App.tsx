import { Navigate, Route, Routes } from "react-router-dom";
import LandingPage from "./pages/LandingPage.tsx";
import SelectTenantPage from "./pages/SelectTenantPage.tsx";

// Route table for the SPA shell. `/` is the landing page, `/select-tenant` is
// the tenant-selection placeholder, and any unknown path redirects to the
// landing page. nginx (try_files fallback) and the Vite dev server both serve
// deep links, so these routes resolve on a hard refresh too.
export default function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/select-tenant" element={<SelectTenantPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
