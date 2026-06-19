import { Navigate, Route, Routes } from "react-router-dom";
import LandingPage from "./pages/LandingPage.tsx";
import SelectTenantPage from "./pages/SelectTenantPage.tsx";
import HowItsBuiltPage from "./pages/HowItsBuiltPage.tsx";
import ShopperSitePage from "./pages/ShopperSitePage.tsx";
import DemoHomePage from "./pages/DemoHomePage.tsx";
import RequireSession from "./components/RequireSession.tsx";

// Route table for the SPA shell. `/`, `/select-tenant`, `/how-its-built`, and the
// public Shopper site (`/site/:slug`) are all public. The Shopper zone sits
// OUTSIDE `RequireSession` — it is unauthenticated and persona-free, the consumer
// storefront where the visitor plays the prospective buyer (Epic 24 adds the
// surface toggle); `/site` with no slug redirects to the tenant picker.
//
// `/app` is the guarded zone: `RequireSession` is its layout route (skeleton while
// `/me` resolves, redirect to `/` when signed-out), and the guarded children
// render through its `<Outlet />`. The zone is nested so P1.7 can add `/app/*`
// children without touching the guard. Any unknown path redirects to the landing
// page; nginx (try_files fallback) and the Vite dev server both serve deep links,
// so these routes resolve on a hard refresh too.
export default function App() {
  return (
    <Routes>
      <Route path="/" element={<LandingPage />} />
      <Route path="/select-tenant" element={<SelectTenantPage />} />
      <Route path="/how-its-built" element={<HowItsBuiltPage />} />
      <Route path="/site" element={<Navigate to="/select-tenant" replace />} />
      <Route path="/site/:slug" element={<ShopperSitePage />} />
      <Route path="/app" element={<RequireSession />}>
        <Route index element={<DemoHomePage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
