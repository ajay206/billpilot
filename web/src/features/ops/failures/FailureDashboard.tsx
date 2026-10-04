import { useEffect, useState } from "react";

import type { Api } from "../../../api";
import { partyName } from "../../../format";
import type { Account } from "../../../types";

type Incident = {
  id: string;
  incidentType: string;
  severity: string;
  status: string;
  title: string;
  accountId: string | null;
};

type StuckRun = {
  id: string;
  runKey: string;
  status: string;
  accountId: string | null;
  error: string | null;
};

type Letter = {
  id: string;
  topic: string;
  eventType: string;
  error: string;
  retryCount: number;
  status: string;
};

type LagTopic = { topic: string; lag: number; pending: number; queued: number; dead: number };

type Snapshot = {
  backend?: string;
  incidents: Incident[];
  stuckRuns: StuckRun[];
  deadLetters: Letter[];
  lag: { topics: LagTopic[] };
};

const EMPTY: Snapshot = { incidents: [], stuckRuns: [], deadLetters: [], lag: { topics: [] } };

function asSnapshot(data: unknown): Snapshot {
  if (!data || Array.isArray(data) || typeof data !== "object") return EMPTY;
  const row = data as Partial<Snapshot>;
  const lag = row.lag && !Array.isArray(row.lag) ? row.lag : { topics: [] };
  return {
    backend: row.backend,
    incidents: Array.isArray(row.incidents) ? row.incidents : [],
    stuckRuns: Array.isArray(row.stuckRuns) ? row.stuckRuns : [],
    deadLetters: Array.isArray(row.deadLetters) ? row.deadLetters : [],
    lag: { topics: Array.isArray(lag.topics) ? lag.topics : [] },
  };
}

export function FailureDashboard({ api, refreshMs = 5000 }: { api: Api; refreshMs?: number }) {
  const [snapshot, setSnapshot] = useState<Snapshot>(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [account, setAccount] = useState<Account | null>(null);

  async function load() {
    const result = await api.get<unknown>("/ops/failures");
    setSnapshot(asSnapshot(result.data));
  }

  useEffect(() => {
    let cancel = false;
    load()
      .catch((reason: Error) => {
        if (!cancel) setError(reason.message);
      });
    if (refreshMs <= 0) {
      return () => {
        cancel = true;
      };
    }
    const handle = window.setInterval(() => {
      load().catch((reason: Error) => {
        if (!cancel) setError(reason.message);
      });
    }, refreshMs);
    return () => {
      cancel = true;
      window.clearInterval(handle);
    };
  }, [api, refreshMs]);

  async function simulate() {
    setBusy(true);
    setError(null);
    try {
      await api.post("/ops/faults/simulate", {});
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Simulate failed.");
    } finally {
      setBusy(false);
    }
  }

  async function replay(id: string) {
    setBusy(true);
    setError(null);
    try {
      await api.post(`/ops/deadLetters/${id}/replay`, {});
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Replay failed.");
    } finally {
      setBusy(false);
    }
  }

  async function openAccount(accountId: string) {
    setError(null);
    try {
      const result = await api.get<Account>(`/tmf-api/accountManagement/v4/billingAccount/${accountId}`);
      setAccount(result.data);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Account lookup failed.");
    }
  }

  return (
    <section className="phase4-panel" aria-label="Failure dashboard">
      <div className="phase4-head">
        <div>
          <h3>Failure dashboard</h3>
          <p className="phase4-meta">
            Incidents, stuck bill runs, the dead-letter queue, and consumer lag
            {snapshot.backend ? ` · ${snapshot.backend}` : ""}.
          </p>
        </div>
        <button className="primary" type="button" onClick={simulate} disabled={busy}>
          Simulate failures
        </button>
      </div>
      {error ? <p className="error">{error}</p> : null}
      <div className="phase4-grid">
        <div className="phase4-block">
          <h4>Incidents</h4>
          {snapshot.incidents.length === 0 ? <p className="empty">No incidents yet.</p> : null}
          <ul className="phase4-list">
            {snapshot.incidents.slice(0, 8).map((incident) => (
              <li key={incident.id}>
                <strong className={`sev-${incident.severity}`}>{incident.severity}</strong> {incident.title}
                <div className="phase4-meta">
                  {incident.incidentType} · {incident.status}
                </div>
                {incident.accountId ? (
                  <button className="text-button" type="button" onClick={() => openAccount(incident.accountId as string)}>
                    Open account
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
        <div className="phase4-block">
          <h4>Stuck runs</h4>
          {snapshot.stuckRuns.length === 0 ? <p className="empty">No stuck bill runs.</p> : null}
          <ul className="phase4-list">
            {snapshot.stuckRuns.map((run) => (
              <li key={run.id}>
                <strong>{run.runKey}</strong>
                <div className="phase4-meta">{run.status}</div>
                {run.accountId ? (
                  <button className="text-button" type="button" onClick={() => openAccount(run.accountId as string)}>
                    Open account
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        </div>
        <div className="phase4-block">
          <h4>Dead letters</h4>
          {snapshot.deadLetters.length === 0 ? <p className="empty">The dead-letter queue is empty.</p> : null}
          <ul className="phase4-list">
            {snapshot.deadLetters.map((letter) => (
              <li key={letter.id}>
                <strong>{letter.eventType}</strong>
                <div className="phase4-meta">
                  {letter.topic} · retries {letter.retryCount} · {letter.status}
                </div>
                <button className="ghost" type="button" onClick={() => replay(letter.id)} disabled={busy}>
                  Replay
                </button>
              </li>
            ))}
          </ul>
        </div>
        <div className="phase4-block">
          <h4>Consumer lag</h4>
          {snapshot.lag.topics.length === 0 ? <p className="empty">No lag snapshot yet.</p> : null}
          <ul className="phase4-list">
            {snapshot.lag.topics.map((topic) => (
              <li key={topic.topic}>
                <strong>{topic.topic}</strong>
                <div className="phase4-meta">lag {topic.lag}</div>
              </li>
            ))}
          </ul>
        </div>
      </div>
      {account ? (
        <p className="phase4-note">
          Account {account.customerNumber} · {partyName(account.relatedParty)} · {account.state}
        </p>
      ) : null}
    </section>
  );
}
