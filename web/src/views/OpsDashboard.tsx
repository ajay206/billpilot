import { useEffect, useState } from "react";

import { ApiError } from "../api";
import type { Api } from "../api";
import { qs } from "../api";
import { DataTable, Metric, Placeholder, StatusBadge } from "../components";
import { inr, whenTime } from "../format";
import type { Adjustment, AgentRun, AuditEntry } from "../types";

type Queue = "credits" | "unbars" | "plans";

export function OpsDashboard({ api }: { api: Api }) {
  const [openDisputes, setOpenDisputes] = useState<number | null>(null);
  const [pending, setPending] = useState<Adjustment[]>([]);
  const [pendingTotal, setPendingTotal] = useState<number | null>(null);
  const [fraud, setFraud] = useState<number | null>(null);
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [queue, setQueue] = useState<Queue>("credits");
  const [notice, setNotice] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function reload(current: Api) {
    const [disputes, adjustments, flags, runRows, auditRows] = await Promise.all([
      current.get<unknown[]>(qs("/tmf-api/customerBillManagement/v4/customerBillDispute", { status: "open", limit: 1 })),
      current.get<Adjustment[]>(
        qs("/tmf-api/customerBillManagement/v4/billAdjustment", { status: "pending_approval", limit: 20 }),
      ),
      current.get<unknown[]>(qs("/tmf-api/accountManagement/v4/fraudFlag", { limit: 1 })),
      current.get<AgentRun[]>("/ops/agentRuns?limit=8"),
      current.get<AuditEntry[]>("/ops/auditLog?limit=8"),
    ]);
    setOpenDisputes(disputes.total);
    setPending(adjustments.data);
    setPendingTotal(adjustments.total);
    setFraud(flags.total);
    setRuns(runRows.data);
    setAudit(auditRows.data);
  }

  useEffect(() => {
    let cancel = false;
    reload(api).catch((reason: Error) => {
      if (!cancel) setError(reason.message);
    });
    return () => {
      cancel = true;
    };
  }, [api]);

  async function decide(id: string, decision: "approve" | "reject") {
    setBusyId(id);
    setNotice(null);
    try {
      const result = await api.post<Adjustment>(
        `/tmf-api/customerBillManagement/v4/billAdjustment/${id}/approve`,
        {
          decision,
          note: decision === "approve" ? "Approved in the ops console." : "Rejected in the ops console.",
        },
      );
      const approver = result.data.decidedBy || "ops";
      setNotice(`${decision === "approve" ? "Approved" : "Rejected"} by ${approver}. Status: ${result.data.status}.`);
      await reload(api);
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 409) {
        setNotice("Already decided. Approving again does not apply the credit twice.");
      } else {
        setNotice(reason instanceof Error ? reason.message : "The decision was not recorded.");
      }
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="ops">
      <header className="panel-head">
        <div>
          <p className="eyebrow">Ops control tower</p>
          <h2>Approvals, runs, and the audit log</h2>
        </div>
      </header>
      {error ? <p className="error">{error}</p> : null}
      <div className="metrics">
        <Metric label="Open disputes" value={openDisputes ?? "—"} hint="Status open" />
        <Metric label="Pending approvals" value={pendingTotal ?? "—"} hint="Credits waiting" />
        <Metric label="Fraud flags" value={fraud ?? "—"} hint="Synthetic flags" />
      </div>

      <section className="queue" aria-label="Approval queue">
        <div className="tabs" role="tablist">
          {(
            [
              ["credits", "Credits"],
              ["unbars", "Unbars"],
              ["plans", "Plan changes"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              role="tab"
              aria-selected={queue === id}
              className={queue === id ? "tab selected" : "tab"}
              onClick={() => setQueue(id)}
            >
              {label}
            </button>
          ))}
        </div>
        {notice ? <p className="notice">{notice}</p> : null}
        {queue === "credits" ? (
          pending.length === 0 ? (
            <p className="empty">No credits are pending approval.</p>
          ) : (
            <ul className="queue-list">
              {pending.map((item) => (
                <li key={item.id} className="queue-item">
                  <div>
                    <div className="proposal-top">
                      <strong>{inr(item.amount)} {item.adjustmentType}</strong>
                      <StatusBadge status={item.status} />
                    </div>
                    <p>{item.reason}</p>
                    <p className="muted">
                      Proposed by {item.proposedBy} · {whenTime(item.creationDate)} · Status: {item.status}
                    </p>
                  </div>
                  <div className="decide">
                    <button type="button" className="primary" disabled={busyId === item.id} onClick={() => decide(item.id, "approve")}>
                      Approve
                    </button>
                    <button type="button" className="ghost" disabled={busyId === item.id} onClick={() => decide(item.id, "reject")}>
                      Reject
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )
        ) : null}
        {queue === "unbars" ? (
          <p className="empty">
            No unbar proposals. The copilot cannot unbar a line, and Phase 1 has no unbar endpoint. Credits use the existing approve endpoint, which records the approver and refuses a second decision.
          </p>
        ) : null}
        {queue === "plans" ? (
          <p className="empty">
            No plan-change proposals. The copilot cannot change a plan. That proposal type is not in the ledger. Credit approve and reject stay on the Phase 1 endpoint.
          </p>
        ) : null}
      </section>

      <section aria-label="Recent agent runs">
        <h3>Recent agent runs</h3>
        <DataTable
          rows={runs}
          empty="No copilot turns yet."
          columns={[
            { key: "when", label: "When", render: (row) => whenTime(row.occurredAt) },
            { key: "who", label: "Persona", render: (row) => row.persona },
            { key: "decision", label: "Decision", render: (row) => row.decision },
            { key: "tokens", label: "Tokens", render: (row) => `${row.promptTokens + row.completionTokens}` },
            { key: "cost", label: "Cost", render: (row) => `$${row.estimatedCostUsd}` },
            { key: "latency", label: "Latency", render: (row) => `${row.latencyMs} ms` },
            { key: "trace", label: "Trace", render: (row) => row.traceId || "—" },
          ]}
        />
      </section>

      <section aria-label="Audit log">
        <h3>Audit log</h3>
        <DataTable
          rows={audit}
          empty="No audit rows."
          columns={[
            { key: "when", label: "When", render: (row) => whenTime(row.occurredAt) },
            { key: "actor", label: "Actor", render: (row) => `${row.actorRole} · ${row.actorId}` },
            { key: "action", label: "Action", render: (row) => row.action },
            { key: "resource", label: "Resource", render: (row) => row.resourceType },
          ]}
        />
      </section>

      <div className="placeholders">
        <Placeholder phase="Phase 4" title="Failure dashboard">
          Live failures, stuck bill runs, and consumer lag. The event publisher is still a no-op, so this panel is a placeholder.
        </Placeholder>
        <Placeholder phase="Phase 4" title="Reports">
          Daily and monthly billing, collections, dispute, and treatment reports are not generated yet.
        </Placeholder>
      </div>
    </div>
  );
}
