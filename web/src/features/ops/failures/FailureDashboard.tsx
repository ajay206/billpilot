import { useEffect, useState } from "react";

import type { Api } from "../../../api";
import { BarChart, DataTable, DonutChart, Metric, SeverityBadge, Skeleton, StatusBadge } from "../../../components";
import { age, partyName } from "../../../format";
import type { Account } from "../../../types";

type Incident = {
  id: string;
  incidentType: string;
  severity: string;
  status: string;
  title: string;
  accountId: string | null;
  holderName: string | null;
  customerNumber: string | null;
  detectedAt: string;
};

type StuckRun = {
  id: string;
  runKey: string;
  status: string;
  accountId: string | null;
  context: string | null;
  holderName: string | null;
  customerNumber: string | null;
  error: string | null;
  startedAt: string;
};

type Letter = {
  id: string;
  topic: string;
  eventType: string;
  error: string;
  retryCount: number;
  status: string;
  createdAt: string;
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

function label(value: string): string {
  return value.replaceAll("_", " ");
}

export function FailureDashboard({
  api,
  refreshMs = 5000,
  onOpenAccount,
}: {
  api: Api;
  refreshMs?: number;
  onOpenAccount?: (account: Account) => void;
}) {
  const [snapshot, setSnapshot] = useState<Snapshot>(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [busy, setBusy] = useState(false);
  const [account, setAccount] = useState<Account | null>(null);

  async function load() {
    const result = await api.get<unknown>("/ops/failures");
    setSnapshot(asSnapshot(result.data));
    setLoaded(true);
  }

  useEffect(() => {
    let cancel = false;
    load()
      .then(() => {
        if (!cancel) setLoaded(true);
      })
      .catch((reason: Error) => {
        if (!cancel) setError(reason.message);
      })
      .finally(() => {
        if (!cancel) setLoading(false);
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
      setNotice("Synthetic failures were published and consumed.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Simulate failed.");
    } finally {
      setBusy(false);
    }
  }

  async function replay(letter: Letter) {
    setBusy(true);
    setError(null);
    try {
      const result = await api.post<{ duplicate: boolean }>(`/ops/deadLetters/${letter.id}/replay`, {});
      await load();
      setNotice(
        result.data.duplicate
          ? `${letter.topic} was already replayed. A second replay does not apply it again.`
          : `Replayed ${letter.eventType} on ${letter.topic}.`,
      );
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
      onOpenAccount?.(result.data);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Account lookup failed.");
    }
  }

  const openIncidents = snapshot.incidents.filter((row) => row.status === "open");
  const severityCount = (name: string) => openIncidents.filter((row) => row.severity === name).length;
  const openLetters = snapshot.deadLetters.filter((row) => row.status !== "replayed").length;
  const maxLag = snapshot.lag.topics.reduce((max, topic) => Math.max(max, topic.lag), 0);

  const severityDonut = [
    { label: "Critical", value: severityCount("critical"), color: "#8d2f2f" },
    { label: "High", value: severityCount("high"), color: "#c0512a" },
    { label: "Medium", value: severityCount("medium"), color: "#7a4e0d" },
    { label: "Low", value: severityCount("low"), color: "#14663d" },
  ].filter((d) => d.value > 0);

  const topicBars = snapshot.lag.topics.slice(0, 8).map((t) => ({
    label: t.topic.split(".").pop() ?? t.topic,
    value: t.lag,
    color: t.lag > 50 ? "#8d2f2f" : t.lag > 10 ? "#7a4e0d" : "var(--accent)",
  }));

  return (
    <section className="panel" aria-label="Failure dashboard">
      <header className="panel-head">
        <div>
          <p className="eyebrow">Operations</p>
          <h1>Failures</h1>
          <p className="muted">
            Open incidents, stuck bill runs, and the dead-letter queue
            {snapshot.backend ? ` · ${snapshot.backend}` : ""}.
          </p>
        </div>
        <button className="primary" type="button" onClick={simulate} disabled={busy}>
          {busy ? "Working…" : "Simulate failures"}
        </button>
      </header>
      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}
      {notice ? (
        <p className="notice" role="status">
          {notice}
        </p>
      ) : null}
      {loading ? <Skeleton rows={4} label="Loading failures" /> : null}
      {!loading && loaded ? (
        <>
          <div className="metrics">
            <Metric label="Open critical" value={severityCount("critical")} hint="Severity critical" />
            <Metric label="Open high" value={severityCount("high")} hint="Severity high" />
            <Metric label="Open medium" value={severityCount("medium")} hint="Severity medium" />
            <Metric label="Open low" value={severityCount("low")} hint="Severity low" />
            <Metric label="Dead letters" value={openLetters} hint="Waiting for replay" />
            <Metric label="Max lag" value={maxLag} hint="Highest topic lag" />
          </div>
          {(severityDonut.length > 0 || topicBars.length > 0) ? (
            <div className="charts-row">
              {severityDonut.length > 0 ? (
                <div className="chart-card">
                  <h3>Open incidents by severity</h3>
                  <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
                    <DonutChart data={severityDonut} size={110} />
                    <div className="chart-legend">
                      {severityDonut.map((d) => (
                        <div key={d.label} className="chart-legend-item">
                          <span className="chart-legend-swatch" style={{ background: d.color }} />
                          <span>{d.label}: {d.value}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              ) : null}
              {topicBars.length > 0 ? (
                <div className="chart-card">
                  <h3>Queue lag by topic</h3>
                  <BarChart data={topicBars} height={140} />
                </div>
              ) : null}
            </div>
          ) : null}
          <h2>Incidents</h2>
          <DataTable
            label="Incidents"
            rows={snapshot.incidents}
            empty="No incidents yet. Simulate failures to publish a synthetic batch."
            columns={[
              { key: "severity", label: "Severity", render: (row) => <SeverityBadge severity={row.severity} />, value: (row) => row.severity },
              { key: "type", label: "Type", render: (row) => label(row.incidentType), value: (row) => row.incidentType },
              {
                key: "account",
                label: "Account",
                render: (row) =>
                  row.accountId ? (
                    <button type="button" className="text-button account-link" onClick={() => void openAccount(row.accountId as string)}>
                      <span>{row.holderName || "Open account"}</span>
                      <span className="muted">{row.customerNumber}</span>
                    </button>
                  ) : (
                    <span className="muted">No account</span>
                  ),
                value: (row) => row.holderName || "",
              },
              { key: "age", label: "Age", render: (row) => age(row.detectedAt), value: (row) => row.detectedAt },
              { key: "status", label: "Status", render: (row) => <StatusBadge status={row.status} />, value: (row) => row.status },
            ]}
          />
          <h2>Stuck bill runs</h2>
          <DataTable
            label="Stuck bill runs"
            rows={snapshot.stuckRuns}
            empty="No stuck bill runs."
            columns={[
              {
                key: "context",
                label: "Bill cycle",
                render: (row) => row.context || "No billing account on this run",
                value: (row) => row.context || row.runKey,
              },
              { key: "age", label: "Age", render: (row) => age(row.startedAt), value: (row) => row.startedAt },
              { key: "status", label: "Status", render: (row) => <StatusBadge status={row.status} />, value: (row) => row.status },
              {
                key: "account",
                label: "Account",
                render: (row) =>
                  row.accountId ? (
                    <button type="button" className="text-button" onClick={() => void openAccount(row.accountId as string)}>
                      Open account
                    </button>
                  ) : (
                    <span className="muted">No account to open</span>
                  ),
                value: (row) => row.customerNumber || "",
              },
            ]}
          />
          <h2>Dead letters</h2>
          <DataTable
            label="Dead letters"
            rows={snapshot.deadLetters}
            empty="The dead-letter queue is empty."
            columns={[
              { key: "topic", label: "Topic", render: (row) => row.topic, value: (row) => row.topic },
              { key: "error", label: "Error", render: (row) => row.error, value: (row) => row.error },
              { key: "age", label: "Age", render: (row) => age(row.createdAt), value: (row) => row.createdAt },
              { key: "status", label: "Status", render: (row) => <StatusBadge status={row.status} />, value: (row) => row.status },
              {
                key: "replay",
                label: "Replay",
                render: (row) => (
                  <button className="primary" type="button" onClick={() => void replay(row)} disabled={busy}>
                    {row.status === "replayed" ? "Replay again" : "Replay"}
                  </button>
                ),
              },
            ]}
          />
          {snapshot.lag.topics.length === 0 ? <p className="empty">No lag snapshot yet.</p> : null}
          {account ? (
            <p className="notice" role="status">
              Account {account.customerNumber} · {partyName(account.relatedParty)} · {account.state}
            </p>
          ) : null}
        </>
      ) : null}
    </section>
  );
}
