import { useEffect, useState } from "react";

import { ApiError } from "../api";
import type { Api } from "../api";
import { qs } from "../api";
import { ConfirmDialog, DataTable, Metric, Skeleton, StatusBadge } from "../components";
import { MigrationDesk } from "../features/migration/MigrationDesk";
import { OnboardingPanel } from "../features/onboarding/OnboardingPanel";
import { FailureDashboard } from "../features/ops/failures/FailureDashboard";
import { FindingsPanel } from "../features/ops/findings/FindingsPanel";
import { ReportsPanel } from "../features/ops/reports/ReportsPanel";
import { actorLabel, inr, partyName, whenTime } from "../format";
import type { Account, Adjustment, AgentRun, AuditEntry } from "../types";

type Queue = "credits" | "unbars" | "plans";
type Decision = { id: string; decision: "approve" | "reject"; amount: string; reason: string };

export function OpsDashboard({
  api,
  section,
  focus,
  onOpenAccount,
  onToast,
}: {
  api: Api;
  section: string;
  focus: Account | null;
  onOpenAccount?: (account: Account) => void;
  onToast?: (text: string, tone?: "ok" | "err") => void;
}) {
  const [loading, setLoading] = useState(true);
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
  const [decision, setDecision] = useState<Decision | null>(null);

  async function reload(current: Api) {
    const [disputes, adjustments, flags, runRows, auditRows] = await Promise.all([
      current.get<unknown[]>(qs("/tmf-api/customerBillManagement/v4/customerBillDispute", { status: "open", limit: 1 })),
      current.get<Adjustment[]>(qs("/tmf-api/customerBillManagement/v4/billAdjustment", { status: "pending_approval", limit: 40 })),
      current.get<unknown[]>(qs("/tmf-api/accountManagement/v4/fraudFlag", { limit: 1 })),
      current.get<AgentRun[]>("/ops/agentRuns?limit=40"),
      current.get<AuditEntry[]>("/ops/auditLog?limit=40"),
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
    setLoading(true);
    reload(api)
      .catch((reason: Error) => {
        if (!cancel) setError(reason.message);
      })
      .finally(() => {
        if (!cancel) setLoading(false);
      });
    return () => {
      cancel = true;
    };
  }, [api]);

  async function decide(next: Decision) {
    setBusyId(next.id);
    setNotice(null);
    try {
      const result = await api.post<Adjustment>(`/tmf-api/customerBillManagement/v4/billAdjustment/${next.id}/approve`, {
        decision: next.decision,
        note: next.decision === "approve" ? "Approved in the ops console." : "Rejected in the ops console.",
      });
      const approver = result.data.decidedBy || "ops";
      const text = `${next.decision === "approve" ? "Approved" : "Rejected"} by ${approver}. Status: ${result.data.status}.`;
      setNotice(text);
      onToast?.(text, "ok");
      await reload(api);
    } catch (reason) {
      const text =
        reason instanceof ApiError && reason.status === 409
          ? "Already decided. Approving again does not apply the credit twice."
          : reason instanceof Error
            ? reason.message
            : "The decision was not recorded.";
      setNotice(text);
      onToast?.(text, "err");
    } finally {
      setBusyId(null);
      setDecision(null);
    }
  }

  return (
    <div className="ops">
      {section === "queue" || section === "overview" ? (
        <header className="panel-head">
          <div>
            <p className="eyebrow">Ops control tower</p>
            <h1>Control tower</h1>
            <p className="muted">Ops has no customer chat. This screen approves proposals and reads the log.</p>
          </div>
        </header>
      ) : null}
      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}
      {focus ? (
        <article className="focus-card">
          <p className="eyebrow">Account in focus</p>
          <h2>{partyName(focus.relatedParty)}</h2>
          <p className="muted">
            {focus.customerNumber} · {focus.name} · {focus.state}
            {focus.treatment ? ` · treatment ${focus.treatment.stage}` : ""}
          </p>
        </article>
      ) : null}
      {loading && section !== "failures" && section !== "reports" && section !== "findings" ? (
        <Skeleton rows={3} label="Loading the control tower" />
      ) : null}
      {!loading && !error && (section === "queue" || section === "overview") ? (
        <>
          <div className="metrics">
            <Metric label="Open disputes" value={openDisputes ?? "—"} hint="Status open" />
            <Metric label="Pending approvals" value={pendingTotal ?? "—"} hint="Credits waiting" />
            <Metric label="Fraud flags" value={fraud ?? "—"} hint="Synthetic flags" />
          </div>
          <section className="panel queue" aria-label="Approval queue">
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
            {notice ? (
              <p className="notice" role="status">
                {notice}
              </p>
            ) : null}
            {queue === "credits" ? (
              pending.length === 0 ? (
                <p className="empty">No credits are pending approval.</p>
              ) : (
                <ul className="queue-list">
                  {pending.map((item) => (
                    <li key={item.id} className="queue-item">
                      <div>
                        <div className="proposal-top">
                          <strong>
                            {inr(item.amount)} {item.adjustmentType}
                          </strong>
                          <StatusBadge status={item.status} />
                        </div>
                        <p>{item.reason}</p>
                        <p className="muted">
                          {item.billingAccount.name ? `${item.billingAccount.name} · ` : ""}
                          Proposed by {actorLabel(item.proposedBy)} · {whenTime(item.creationDate)}
                        </p>
                      </div>
                      <div className="decide">
                        <button
                          type="button"
                          className="primary"
                          disabled={busyId === item.id}
                          onClick={() =>
                            setDecision({
                              id: item.id,
                              decision: "approve",
                              amount: inr(item.amount),
                              reason: item.reason,
                            })
                          }
                        >
                          Approve
                        </button>
                        <button
                          type="button"
                          className="ghost"
                          disabled={busyId === item.id}
                          onClick={() =>
                            setDecision({
                              id: item.id,
                              decision: "reject",
                              amount: inr(item.amount),
                              reason: item.reason,
                            })
                          }
                        >
                          Reject
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              )
            ) : null}
            {queue === "unbars" ? (
              <p className="empty">No unbar proposals. Unbars are a Phase 4 placeholder. Credits stay on this queue until ops confirms them.</p>
            ) : null}
            {queue === "plans" ? (
              <p className="empty">No plan-change proposals. Plan changes are a Phase 4 placeholder.</p>
            ) : null}
          </section>
        </>
      ) : null}
      {section === "failures" ? <FailureDashboard api={api} onOpenAccount={onOpenAccount} /> : null}
      {section === "reports" ? <ReportsPanel api={api} /> : null}
      {section === "findings" ? <FindingsPanel api={api} onOpenAccount={onOpenAccount} /> : null}
      {!loading && !error && section === "runs" ? (
        <section className="panel" aria-label="Recent agent runs">
          <h2>Recent agent runs</h2>
          <DataTable
            label="Agent runs"
            rows={runs}
            empty="No copilot turns yet."
            columns={[
              { key: "when", label: "When", render: (row) => whenTime(row.occurredAt), value: (row) => row.occurredAt },
              { key: "who", label: "Persona", render: (row) => row.persona, value: (row) => row.persona },
              { key: "decision", label: "Decision", render: (row) => row.decision, value: (row) => row.decision },
              {
                key: "tokens",
                label: "Tokens",
                render: (row) => `${row.promptTokens + row.completionTokens}`,
                value: (row) => row.promptTokens + row.completionTokens,
              },
              { key: "cost", label: "Cost", render: (row) => `$${row.estimatedCostUsd}`, value: (row) => Number(row.estimatedCostUsd) },
              { key: "latency", label: "Latency", render: (row) => `${row.latencyMs} ms`, value: (row) => row.latencyMs },
              { key: "trace", label: "Trace", render: (row) => row.traceId || "—", value: (row) => row.traceId || "" },
            ]}
          />
        </section>
      ) : null}
      {!loading && !error && section === "audit" ? (
        <section className="panel" aria-label="Audit log">
          <h2>Audit log</h2>
          <DataTable
            label="Audit log"
            rows={audit}
            empty="No audit rows."
            columns={[
              { key: "when", label: "When", render: (row) => whenTime(row.occurredAt), value: (row) => row.occurredAt },
              { key: "actor", label: "Actor", render: (row) => `${row.actorRole} · ${row.actorId}`, value: (row) => row.actorId },
              { key: "action", label: "Action", render: (row) => row.action, value: (row) => row.action },
              { key: "resource", label: "Resource", render: (row) => row.resourceType, value: (row) => row.resourceType },
              {
                key: "request",
                label: "Request",
                render: (row) => <code title={row.requestId}>{row.requestId.slice(0, 8)}</code>,
                value: (row) => row.requestId,
              },
            ]}
          />
        </section>
      ) : null}
      {decision ? (
        <ConfirmDialog
          title={decision.decision === "approve" ? "Approve this credit?" : "Reject this credit?"}
          body={
            decision.decision === "approve"
              ? `Approve ${decision.amount}. ${decision.reason} This applies the credit to the bill. It cannot be applied twice.`
              : `Reject ${decision.amount}. ${decision.reason} The bill does not change.`
          }
          confirmLabel={decision.decision === "approve" ? "Confirm approval" : "Confirm rejection"}
          busy={busyId === decision.id}
          onCancel={() => setDecision(null)}
          onConfirm={() => void decide(decision)}
        />
      ) : null}
      {!loading && !error && section === "onboarding" ? <OnboardingPanel api={api} /> : null}
      {!loading && !error && section === "migration" ? <MigrationDesk api={api} /> : null}
    </div>
  );
}
