import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { EventsIsland } from "./EventsIsland";
import "../app.css";

const container = document.getElementById("events-island");
if (container) {
  createRoot(container).render(
    <StrictMode>
      <EventsIsland />
    </StrictMode>,
  );
}
