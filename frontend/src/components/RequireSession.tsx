import { Navigate, Outlet } from "react-router-dom";
import PageLayout from "./PageLayout.tsx";
import AppShell from "./AppShell.tsx";
import { useSession } from "../session";

// Route guard for the `/app` zone. A react-router v6 layout-route guard: it sits
// at `/app` and decides, from the session status, whether to render the guarded
// children (`<Outlet />`), wait for `/me` to resolve, or send a signed-out
// visitor back to the landing page.
//
//   - loading    -> a quiet "restoring your session" skeleton while `/me` is in
//                   flight, so the guard never flashes a redirect before the
//                   session is known.
//   - signed-out -> redirect to `/` with `replace` so the guarded URL does not
//                   pollute history (no back-button loop into a blocked page).
//   - signed-in  -> render the guarded children.
export default function RequireSession() {
  const { status } = useSession();

  if (status === "loading") {
    return (
      <PageLayout pageId="app-loading">
        <div
          id="app-session-skeleton"
          className="app-session-skeleton"
          role="status"
          aria-live="polite"
        >
          <p
            id="app-session-skeleton-message"
            className="app-session-skeleton-message"
          >
            Restoring your session…
          </p>
        </div>
      </PageLayout>
    );
  }

  if (status === "signed-out") {
    return <Navigate to="/" replace />;
  }

  // Signed in: wrap the routed content in the branded app shell (masthead +
  // theming) so every guarded surface renders inside the chrome.
  return (
    <AppShell>
      <Outlet />
    </AppShell>
  );
}
