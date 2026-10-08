import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { initPlatform } from "./platform";
import "./styles.css";

void initPlatform();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
