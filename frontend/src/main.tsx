import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App.tsx";
import { SessionProvider } from "./session";
import "./styles/tokens.css";
import "./styles/base.css";
import "./styles/button.css";
import "./styles/card.css";
import "./styles/stamp-tag.css";
import "./styles/popover.css";
import "./styles/persona-chip.css";
import "./styles/app-shell.css";
import "./styles/left-nav.css";
import "./styles/pages.css";

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("Root element #root was not found in index.html");
}

createRoot(rootElement).render(
  <StrictMode>
    <BrowserRouter>
      <SessionProvider>
        <App />
      </SessionProvider>
    </BrowserRouter>
  </StrictMode>,
);
