import { useEffect, useState } from "react";

import type { Api } from "../api";
import { qs } from "../api";
import { AnswerText, DataTable, Placeholder, PolicyDrawer, ProposalCard, Skeleton, StatusBadge } from "../components";
import { characteristic, inr, partyName, when, whenTime } from "../format";
import type {
  Account,
  Adjustment,
  Bill,
  ChatResponse,
  Citation,
  Dispute,
  Payment,
  Proposed,
  Rate,
  Ticket,
  ToolCall,
  Usage,
} from "../types";

type Tab = "bills" | "lines" | "usage" | "payments" | "treatment" | "tickets" | "disputes";

type Turn = {
  id: string;
  role: "user" | "assistant";
  text: string;
  citations?: Citation[];
  proposed?: Proposed[];
  toolCalls?: ToolCall[];
};

const TABS: { id: Tab; label: string }[] = [
  { id: "bills", label: "Bills" },
  { id: "lines", label: "Lines" },
  { id: "usage", label: "Usage" },
  { id: "payments", label: "Payments" },
  { id: "treatment", label: "Treatment" },
  { id: "tickets", label: "Tickets" },
  { id: "disputes", label: "Disputes" },
];

export function CsrConsole({ api, account }: { api: Api; account: Account | null }) {
  const [tab, setTab] = useState<Tab>("bills");
  const [loading, setLoading] = useState(false);
  const [bills, setBills] = useState<Bill[]>([]);
  const [lines, setLines] = useState<Rate[]>([]);
  const [usage, setUsage] = useState<Usage[]>([]);
  const [payments, setPayments] = useState<Payment[]>([]);
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [disputes, setDisputes] = useState<Dispute[]>([]);
  const [adjustments, setAdjustments] = useState<Adjustment[]>([]);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState(
    "Investigate this account and propose a credit only if the bill shows a duplicate line. Do not apply it.",
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [citation, setCitation] = useState<{ doc: string; section: string } | null>(null);
  const [openTools, setOpenTools] = useState<string | null>(null);

  useEffect(() => {
    setTurns([]);
    setTab("bills");
    if (!account) {
      setBills([]);
      setUsage([]);
      setPayments([]);
      setTickets([]);
      setDisputes([]);
      setAdjustments([]);
      return;
    }
    let cancel = false;
    setLoading(true);
    const id = account.id;
    Promise.all([
      api.get<Bill[]>(qs("/tmf-api/customerBillManagement/v4/customerBill", { "billingAccount.id": id, limit: 24 })),
      api.get<Usage[]>(qs("/tmf-api/usageManagement/v4/usage", { "billingAccount.id": id, limit: 24 })),
      api.get<Payment[]>(qs("/tmf-api/paymentManagement/v4/payment", { "account.id": id, limit: 24 })),
      api.get<Ticket[]>(qs("/tmf-api/troubleTicket/v4/troubleTicket", { "billingAccount.id": id, limit: 24 })),
      api.get<Dispute[]>(qs("/tmf-api/customerBillManagement/v4/customerBillDispute", { "billingAccount.id": id, limit: 24 })),
      api.get<Adjustment[]>(qs("/tmf-api/customerBillManagement/v4/billAdjustment", { "billingAccount.id": id, limit: 24 })),
    ])
      .then(([billRows, usageRows, paymentRows, ticketRows, disputeRows, adjustmentRows]) => {
        if (cancel) return;
        setBills(billRows.data);
        setUsage(usageRows.data);
        setPayments(paymentRows.data);
        setTickets(ticketRows.data);
        setDisputes(disputeRows.data);
        setAdjustments(adjustmentRows.data);
      })
      .catch((reason: Error) => {
        if (!cancel) setError(reason.message);
      })
      .finally(() => {
        if (!cancel) setLoading(false);
      });
    return () => {
      cancel = true;
    };
  }, [api, account]);

  useEffect(() => {
    const billId = bills[0]?.id;
    if (!account || !billId) {
      setLines([]);
      return;
    }
    let cancel = false;
    api
      .get<Rate[]>(
        qs("/tmf-api/customerBillManagement/v4/appliedCustomerBillingRate", {
          "billingAccount.id": account.id,
          "bill.id": billId,
          limit: 40,
        }),
      )
      .then((result) => {
        if (!cancel) setLines(result.data);
      })
      .catch((reason: Error) => {
        if (!cancel) setError(reason.message);
      });
    return () => {
      cancel = true;
    };
  }, [api, account, bills]);

  async function send() {
    if (!account || busy || !draft.trim()) return;
    const message = draft.trim();
    setBusy(true);
    setError(null);
    setTurns((current) => [...current, { id: `user-${Date.now()}`, role: "user", text: message }]);
    try {
      const result = await api.post<ChatResponse>("/agent/chat", { message, accountId: account.id });
      setTurns((current) => [
        ...current,
        {
          id: result.data.runId,
          role: "assistant",
          text: result.data.answer,
          citations: result.data.citations,
          proposed: result.data.proposedActions,
          toolCalls: result.data.toolCalls,
        },
      ]);
      setOpenTools(result.data.runId);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The copilot did not answer.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="workspace csr">
      <section className="panel dossier" aria-label="Account dossier">
        {!account ? <p className="empty">Search for an account to open the 360 view.</p> : null}
        {account ? (
          <>
            <header className="account-hero">
              <div>
                <p className="eyebrow">Account 360</p>
                <h1>{partyName(account.relatedParty)}</h1>
                <p className="muted">
                  {account.customerNumber} · {account.name}
                </p>
              </div>
              <StatusBadge status={account.state} />
            </header>
            <dl className="facts">
              <div>
                <dt>Status</dt>
                <dd>{account.state}</dd>
              </div>
              <div>
                <dt>Treatment</dt>
                <dd>{account.treatment ? `${account.treatment.stage} · ${account.treatment.status}` : "None"}</dd>
              </div>
              <div>
                <dt>Hold</dt>
                <dd>{account.treatment?.holdReason || "No hold"}</dd>
              </div>
              <div>
                <dt>Exemption</dt>
                <dd>{account.exemption?.reason || "None"}</dd>
              </div>
            </dl>
            <div className="tabs" role="tablist" aria-label="Account sections">
              {TABS.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  role="tab"
                  aria-selected={tab === item.id}
                  className={tab === item.id ? "tab selected" : "tab"}
                  onClick={() => setTab(item.id)}
                >
                  {item.label}
                </button>
              ))}
            </div>
            {loading ? <Skeleton rows={4} label="Loading account" /> : null}
            {!loading && tab === "bills" ? (
              <DataTable
                label="Bills"
                rows={bills}
                empty="No bills in scope."
                columns={[
                  { key: "bill", label: "Bill", render: (row) => row.billNo, value: (row) => row.billNo },
                  { key: "date", label: "Date", render: (row) => when(row.billDate), value: (row) => row.billDate },
                  { key: "state", label: "State", render: (row) => <StatusBadge status={row.state} />, value: (row) => row.state },
                  { key: "total", label: "Total", render: (row) => inr(row.taxIncludedAmount), value: (row) => Number(row.taxIncludedAmount.value) },
                  { key: "due", label: "Due", render: (row) => inr(row.amountDue), value: (row) => Number(row.amountDue.value) },
                ]}
              />
            ) : null}
            {!loading && tab === "lines" ? (
              <DataTable
                label="Lines"
                rows={lines}
                empty="No lines on the latest bill."
                columns={[
                  { key: "name", label: "Line", render: (row) => row.name, value: (row) => row.name },
                  { key: "type", label: "Type", render: (row) => row.appliedBillingRateType, value: (row) => row.appliedBillingRateType },
                  { key: "amount", label: "Amount", render: (row) => inr(row.taxExcludedAmount), value: (row) => Number(row.taxExcludedAmount.value) },
                ]}
              />
            ) : null}
            {!loading && tab === "usage" ? (
              <DataTable
                label="Usage"
                rows={usage}
                empty="No usage in the latest page."
                columns={[
                  { key: "when", label: "When", render: (row) => whenTime(row.usageDate), value: (row) => row.usageDate },
                  { key: "what", label: "Usage", render: (row) => row.description, value: (row) => row.description },
                  { key: "type", label: "Type", render: (row) => row.usageType, value: (row) => row.usageType },
                  {
                    key: "rated",
                    label: "Rated",
                    render: (row) => characteristic(row.usageCharacteristic, "ratedAmount"),
                    value: (row) => characteristic(row.usageCharacteristic, "ratedAmount"),
                  },
                ]}
              />
            ) : null}
            {!loading && tab === "payments" ? (
              <DataTable
                label="Payments"
                rows={payments}
                empty="No payments."
                columns={[
                  { key: "date", label: "Date", render: (row) => when(row.paymentDate), value: (row) => row.paymentDate },
                  { key: "status", label: "Status", render: (row) => <StatusBadge status={row.status} />, value: (row) => row.status },
                  { key: "method", label: "Method", render: (row) => row.paymentMethod?.name || "—", value: (row) => row.paymentMethod?.name || "" },
                  { key: "amount", label: "Amount", render: (row) => inr(row.amount), value: (row) => Number(row.amount.value) },
                ]}
              />
            ) : null}
            {!loading && tab === "treatment" ? (
              <div className="treatment">
                {account.treatment ? (
                  <>
                    <p>
                      Stage <strong>{account.treatment.stage}</strong> · status <strong>{account.treatment.status}</strong>
                    </p>
                    <p className="muted">
                      {account.treatment.holdReason ? `Hold: ${account.treatment.holdReason}. ` : "No hold. "}
                      Started {when(account.treatment.startedAt)}.
                    </p>
                  </>
                ) : (
                  <p>No active treatment.</p>
                )}
                {account.exemption ? <p>Exemption: {account.exemption.reason}</p> : null}
              </div>
            ) : null}
            {!loading && tab === "tickets" ? (
              <DataTable
                label="Tickets"
                rows={tickets}
                empty="No open tickets on this page."
                columns={[
                  { key: "name", label: "Ticket", render: (row) => row.name, value: (row) => row.name },
                  { key: "status", label: "Status", render: (row) => row.status, value: (row) => row.status },
                  { key: "severity", label: "Severity", render: (row) => row.severity, value: (row) => row.severity },
                  { key: "when", label: "Opened", render: (row) => when(row.creationDate), value: (row) => row.creationDate },
                ]}
              />
            ) : null}
            {!loading && tab === "disputes" ? (
              <div className="stack">
                {disputes.map((dispute) => (
                  <article key={dispute.id} className="proposal">
                    <div className="proposal-top">
                      <strong>{dispute.category}</strong>
                      <StatusBadge status={dispute.status} />
                    </div>
                    <p>{dispute.description}</p>
                    <p className="proposal-status">Status: {dispute.status}</p>
                  </article>
                ))}
                {adjustments.map((adjustment) => (
                  <article key={adjustment.id} className="proposal">
                    <div className="proposal-top">
                      <strong>{adjustment.adjustmentType}</strong>
                      <StatusBadge status={adjustment.status} />
                    </div>
                    <p className="proposal-amount">{inr(adjustment.amount)}</p>
                    <p>{adjustment.reason}</p>
                    <p className="proposal-status">Status: {adjustment.status}</p>
                  </article>
                ))}
                {disputes.length === 0 && adjustments.length === 0 ? <p className="empty">No disputes or credits.</p> : null}
              </div>
            ) : null}
          </>
        ) : null}
        <Placeholder phase="Phase 4" title="CSR troubleshooting AI">
          Paste an error and get numbered steps from the runbooks. That assistant is not in this build. The copilot beside this panel already cites the same runbook pages.
        </Placeholder>
      </section>
      <section className="panel copilot" aria-label="CSR copilot">
        <p className="eyebrow">Copilot</p>
        <h2>Propose, don’t apply</h2>
        <p className="muted">Credits stay pending until ops approves them. Citations, evidence, and tool calls stay with the answer.</p>
        <div className="thread slim">
          {turns.map((turn) => (
            <article key={turn.id} className={`bubble ${turn.role}`}>
              <p className="who">{turn.role === "user" ? "You" : "BillPilot"}</p>
              {turn.role === "assistant" ? (
                <AnswerText text={turn.text} onCite={(doc, section) => setCitation({ doc, section })} />
              ) : (
                <p>{turn.text}</p>
              )}
              {turn.proposed?.map((item) => (
                <ProposalCard key={`${item.type}-${item.id}`} item={item} />
              ))}
              {turn.citations && turn.citations.length > 0 ? (
                <div className="cite-row">
                  {turn.citations.map((item) => (
                    <button key={`${item.doc}-${item.section}`} type="button" className="cite" onClick={() => setCitation(item)}>
                      {item.doc} · {item.section}
                    </button>
                  ))}
                </div>
              ) : null}
              {turn.toolCalls && turn.toolCalls.length > 0 ? (
                <div className="tools">
                  <button type="button" className="text-button" onClick={() => setOpenTools(openTools === turn.id ? null : turn.id)}>
                    {turn.toolCalls.length} tool call{turn.toolCalls.length === 1 ? "" : "s"}
                  </button>
                  {openTools === turn.id ? (
                    <ol>
                      {turn.toolCalls.map((call, index) => (
                        <li key={`${call.name}-${index}`}>
                          <strong>{call.name}</strong>
                          <span className={call.ok ? "ok" : "bad-text"}>{call.ok ? "ok" : `status ${call.status ?? "—"}`}</span>
                          <code>{JSON.stringify(call.arguments ?? {})}</code>
                          {call.preview ? (
                            <>
                              <span className="evidence-label">Evidence</span>
                              <pre className="evidence">{call.preview}</pre>
                            </>
                          ) : null}
                        </li>
                      ))}
                    </ol>
                  ) : null}
                </div>
              ) : null}
            </article>
          ))}
          {busy ? <p className="muted">Reading the account…</p> : null}
          {error ? <p className="error">{error}</p> : null}
        </div>
        <form
          className="composer"
          onSubmit={(event) => {
            event.preventDefault();
            void send();
          }}
        >
          <label className="sr-only" htmlFor="csr-message">
            Ask the copilot
          </label>
          <textarea id="csr-message" value={draft} rows={4} onChange={(event) => setDraft(event.target.value)} />
          <button type="submit" className="primary" disabled={!account || busy}>
            Ask
          </button>
        </form>
      </section>
      {citation ? (
        <PolicyDrawer api={api} doc={citation.doc} section={citation.section} onClose={() => setCitation(null)} />
      ) : null}
    </div>
  );
}
