import { useEffect, useState } from "react";

import type { Api } from "../../../api";

type Finding = {
  id: string;
  name: string;
  detector: string;
  anomalyType: string;
  family: string;
  severity: string;
  status: string;
  summary: string;
  accountId: string;
  evidence: Record<string, unknown>;
  ticketId: string | null;
  adjustmentId: string | null;
};

function asFindings(data: unknown): Finding[] {
  if (Array.isArray(data)) return data as Finding[];
  if (data && typeof data === "object" && Array.isArray((data as { rows?: unknown }).rows)) {
    return (data as { rows: Finding[] }).rows;
  }
  return [];
}

function hasAmount(evidence: Record<string, unknown>): boolean {
  const raw = evidence.pre_tax_amount ?? evidence.preTaxAmount;
  if (raw == null || raw === "") return false;
  const amount = Number(raw);
  return Number.isFinite(amount) && amount > 0;
}

export function FindingsPanel({ api }: { api: Api }) {
  const [rows, setRows] = useState<Finding[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function load() {
    const result = await api.get<unknown>("/ops/findings");
    setRows(asFindings(result.data));
  }

  useEffect(() => {
    let cancel = false;
    load().catch((reason: Error) => {
      if (!cancel) setError(reason.message);
    });
    return () => {
      cancel = true;
    };
  }, [api]);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      const result = await api.post<unknown>("/ops/assurance/run", {});
      setRows(asFindings(result.data));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The checks failed.");
    } finally {
      setBusy(false);
    }
  }

  async function openCase(id: string) {
    setBusy(true);
    setError(null);
    try {
      const result = await api.post<{ ticketNumber: string; duplicate: boolean }>(`/ops/findings/${id}/case`, {});
      setNotice(
        result.data.duplicate
          ? `Case ${result.data.ticketNumber} was already open.`
          : `Opened case ${result.data.ticketNumber}. It does not move money.`,
      );
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not open a case.");
    } finally {
      setBusy(false);
    }
  }

  async function propose(id: string) {
    setBusy(true);
    setError(null);
    try {
      const result = await api.post<{ status: string; amount: string; duplicate: boolean }>(
        `/ops/findings/${id}/adjustment`,
        {},
      );
      setNotice(
        `Credit ${result.data.amount} is ${result.data.status}. A different approver has to decide. This ops key cannot approve its own proposal.`,
      );
      await load();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not propose a credit.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="phase4-panel" aria-label="Fraud and revenue findings">
      <div className="phase4-head">
        <div>
          <h3>Fraud and revenue findings</h3>
          <p className="phase4-meta">Rule checks over the synthetic ledger. Each row keeps the evidence the query returned.</p>
        </div>
        <button className="primary" type="button" onClick={run} disabled={busy}>
          Run checks
        </button>
      </div>
      <p className="phase4-note">
        Opening a case does not change a bill. A proposed credit stays pending until a different approver decides it.
      </p>
      {error ? <p className="error">{error}</p> : null}
      {notice ? <p className="phase4-note">{notice}</p> : null}
      {rows.length === 0 ? <p className="empty">No findings yet.</p> : null}
      <ul className="phase4-list">
        {rows.slice(0, 12).map((finding) => (
          <li key={finding.id}>
            <strong className={`sev-${finding.severity}`}>{finding.severity}</strong> {finding.name}
            <div className="phase4-meta">
              {finding.family} · {finding.anomalyType} · {finding.status}
            </div>
            <p>{finding.summary}</p>
            <p className="phase4-meta">{JSON.stringify(finding.evidence)}</p>
            <div className="phase4-actions">
              <button className="ghost" type="button" onClick={() => openCase(finding.id)} disabled={busy}>
                Open case
              </button>
              {hasAmount(finding.evidence) ? (
                <button className="ghost" type="button" onClick={() => propose(finding.id)} disabled={busy}>
                  Propose adjustment
                </button>
              ) : null}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
