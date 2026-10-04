import { useEffect, useMemo, useState } from "react";

import { createApi } from "./api";
import { personaById, personaFromPath, PERSONAS, personaPath } from "./personas";
import type { PersonaId } from "./personas";
import type { Health } from "./types";
import { CsrConsole } from "./views/CsrConsole";
import { CustomerChat } from "./views/CustomerChat";
import { OpsDashboard } from "./views/OpsDashboard";

export function App() {
  const [persona, setPersona] = useState<PersonaId>(() => personaFromPath(window.location.pathname));
  const [health, setHealth] = useState<Health | null>(null);
  const api = useMemo(() => createApi(personaById(persona).key), [persona]);

  useEffect(() => {
    const onPop = () => setPersona(personaFromPath(window.location.pathname));
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  function selectPersona(id: PersonaId) {
    setPersona(id);
    const path = personaPath(id);
    if (window.location.pathname !== path) {
      window.history.pushState({ persona: id }, "", path);
    }
  }

  useEffect(() => {
    let cancel = false;
    fetch("/health")
      .then((response) => response.json())
      .then((body: Health) => {
        if (!cancel) setHealth(body);
      })
      .catch(() => {
        if (!cancel) setHealth(null);
      });
    return () => {
      cancel = true;
    };
  }, []);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="mark" aria-hidden="true">
            Bp
          </span>
          <div>
            <p className="wordmark">BillPilot</p>
            <p className="tag">Synthetic telecom billing</p>
          </div>
        </div>
        <div className="switcher" role="radiogroup" aria-label="Persona">
          {PERSONAS.map((item) => (
            <button
              key={item.id}
              type="button"
              role="radio"
              aria-checked={persona === item.id}
              className={persona === item.id ? "persona selected" : "persona"}
              onClick={() => selectPersona(item.id)}
            >
              <strong>{item.label}</strong>
              <span>{item.scope}</span>
            </button>
          ))}
        </div>
      </header>
      {health?.demoMode ? (
        <div className="banner" role="status">
          Demo mode. The copilot is using the scripted model, so this session needs no model key. Set LLM_BACKEND=api and
          LLM_API_KEY on the server to use a hosted model.
        </div>
      ) : health ? (
        <div className="banner live" role="status">
          Hosted model {health.llmBackend === "api" ? "on" : health.llmBackend}.
          {health.tracing ? " Langfuse tracing is on." : ""}
        </div>
      ) : null}
      <main>
        {persona === "customer" ? <CustomerChat api={api} /> : null}
        {persona === "csr" ? <CsrConsole api={api} /> : null}
        {persona === "ops" ? <OpsDashboard api={api} /> : null}
      </main>
      <footer>
        Learning mock on synthetic data. Not a certified TM Forum implementation. Money and service changes stay pending
        until a person approves them.
      </footer>
    </div>
  );
}
