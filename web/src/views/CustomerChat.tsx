import { useEffect, useState } from "react";

import type { Api } from "../api";
import { qs } from "../api";
import { AnswerText, DataTable, Metric, PolicyDrawer, ProposalCard, Skeleton, StatusBadge } from "../components";
import { inr, partyName, when } from "../format";
import type { Account, Adjustment, Bill, ChatResponse, Citation, Dispute, Payment, Proposed, ToolCall, Usage } from "../types";

type Turn = {
  id: string;
  role: "user" | "assistant";
  text: string;
  citations?: Citation[];
  proposed?: Proposed[];
  toolCalls?: ToolCall[];
};

const PROMPTS = [
  "Why is my bill higher this month? Explain it line by line.",
  "I think I was charged twice. Please open a dispute.",
  "What are the roaming rules for charges outside the home network?",
  "Check my payments, including any failed autopay.",
  "How much allowance do I have left on this account?",
  "What are the refund, deposit, and porting rules?",
  "Did I opt into a value-added service, and what plan am I on?",
];

const TITLES: Record<string, string> = {
  overview: "Your account",
  bills: "Bills",
  usage: "Usage",
  payments: "Payments",
  disputes: "Disputes",
};

export function CustomerPortal({ api, section }: { api: Api; section: string }) {
  const [account, setAccount] = useState<Account | null>(null);
  const [bills, setBills] = useState<Bill[]>([]);
  const [usage, setUsage] = useState<Usage[]>([]);
  const [payments, setPayments] = useState<Payment[]>([]);
  const [disputes, setDisputes] = useState<Dispute[]>([]);
  const [adjustments, setAdjustments] = useState<Adjustment[]>([]);
  const [loading, setLoading] = useState(true);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [citation, setCitation] = useState<{ doc: string; section: string } | null>(null);

  async function loadAccount(current: Api) {
    const accounts = await current.get<Account[]>(qs("/tmf-api/accountManagement/v4/billingAccount", { limit: 5 }));
    const next = accounts.data[0] ?? null;
    setAccount(next);
    if (!next) {
      setBills([]);
      setUsage([]);
      setPayments([]);
      setDisputes([]);
      setAdjustments([]);
      return;
    }
    const [billRows, usageRows, paymentRows, disputeRows, adjustmentRows] = await Promise.all([
      current.get<Bill[]>(qs("/tmf-api/customerBillManagement/v4/customerBill", { "billingAccount.id": next.id, limit: 24 })),
      current.get<Usage[]>(qs("/tmf-api/usageManagement/v4/usage", { "billingAccount.id": next.id, limit: 24 })),
      current.get<Payment[]>(qs("/tmf-api/paymentManagement/v4/payment", { "account.id": next.id, limit: 24 })),
      current.get<Dispute[]>(qs("/tmf-api/customerBillManagement/v4/customerBillDispute", { "billingAccount.id": next.id, limit: 24 })),
      current.get<Adjustment[]>(qs("/tmf-api/customerBillManagement/v4/billAdjustment", { "billingAccount.id": next.id, limit: 24 })),
    ]);
    setBills(billRows.data);
    setUsage(usageRows.data);
    setPayments(paymentRows.data);
    setDisputes(disputeRows.data);
    setAdjustments(adjustmentRows.data);
  }

  useEffect(() => {
    let cancel = false;
    setLoading(true);
    loadAccount(api)
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

  async function send(text: string) {
    const message = text.trim();
    if (!message || busy) return;
    setDraft("");
    setError(null);
    setBusy(true);
    setTurns((current) => [...current, { id: `user-${Date.now()}`, role: "user", text: message }]);
    try {
      const result = await api.post<ChatResponse>("/agent/chat", { message, accountId: account?.id });
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
      await loadAccount(api);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "The copilot did not answer.");
    } finally {
      setBusy(false);
    }
  }

  const name = account ? partyName(account.relatedParty) : "Your account";
  const latest = bills[0];
  const openDisputes = disputes.filter((row) => row.status === "open").length;

  return (
    <div className="workspace customer">
      <section className="panel" aria-label="Self service">
        <header className="panel-head">
          <div>
            <p className="eyebrow">Self service</p>
            <h1>{TITLES[section] ?? "Your account"}</h1>
            <p className="muted">{account ? `${name} · ${account.customerNumber} · ${account.name}` : "Your billing account"}</p>
          </div>
          {account ? <StatusBadge status={account.state} /> : null}
        </header>
        {error ? <p className="error">{error}</p> : null}
        {loading ? <Skeleton rows={5} label="Loading your account" /> : null}
        {!loading && !account ? <p className="empty">No account is linked to this sign-in.</p> : null}
        {!loading && account && section === "overview" ? (
          <>
            <div className="metrics">
              <Metric label="Latest bill" value={latest ? inr(latest.taxIncludedAmount) : "—"} hint={latest?.billNo} />
              <Metric label="Amount due" value={latest ? inr(latest.amountDue) : "—"} hint={latest ? when(latest.billDate) : undefined} />
              <Metric label="Open disputes" value={openDisputes} hint="Waiting on review" />
            </div>
            {latest ? (
              <article className="bill-chip">
                <span>Bill {latest.billNo}</span>
                <strong>{inr(latest.taxIncludedAmount)}</strong>
                <span>
                  Due {inr(latest.amountDue)} · <StatusBadge status={latest.state} />
                </span>
              </article>
            ) : (
              <p className="empty">No bills yet.</p>
            )}
            {adjustments.length > 0 ? (
              <div className="stack">
                <h2>Credits</h2>
                {adjustments.map((adjustment) => (
                  <article key={adjustment.id} className="proposal">
                    <div className="proposal-top">
                      <strong>{adjustment.adjustmentType === "credit" ? "Credit" : "Debit"}</strong>
                      <StatusBadge status={adjustment.status} />
                    </div>
                    <p className="proposal-amount">{inr(adjustment.amount)}</p>
                    <p>{adjustment.reason}</p>
                  </article>
                ))}
              </div>
            ) : null}
          </>
        ) : null}
        {!loading && account && section === "bills" ? (
          <DataTable
            label="Bills"
            rows={bills}
            empty="No bills on this account."
            columns={[
              { key: "bill", label: "Bill", render: (row) => row.billNo, value: (row) => row.billNo },
              { key: "date", label: "Date", render: (row) => when(row.billDate), value: (row) => row.billDate },
              { key: "state", label: "State", render: (row) => <StatusBadge status={row.state} />, value: (row) => row.state },
              { key: "total", label: "Total", render: (row) => inr(row.taxIncludedAmount), value: (row) => Number(row.taxIncludedAmount.value) },
              { key: "due", label: "Due", render: (row) => inr(row.amountDue), value: (row) => Number(row.amountDue.value) },
            ]}
          />
        ) : null}
        {!loading && account && section === "usage" ? (
          <DataTable
            label="Usage"
            rows={usage}
            empty="No usage on this page."
            columns={[
              { key: "when", label: "When", render: (row) => when(row.usageDate), value: (row) => row.usageDate },
              { key: "what", label: "Usage", render: (row) => row.description, value: (row) => row.description },
              { key: "type", label: "Type", render: (row) => row.usageType, value: (row) => row.usageType },
            ]}
          />
        ) : null}
        {!loading && account && section === "payments" ? (
          <DataTable
            label="Payments"
            rows={payments}
            empty="No payments on this account."
            columns={[
              { key: "date", label: "Date", render: (row) => when(row.paymentDate), value: (row) => row.paymentDate },
              { key: "status", label: "Status", render: (row) => <StatusBadge status={row.status} />, value: (row) => row.status },
              { key: "method", label: "Method", render: (row) => row.paymentMethod?.name || "—", value: (row) => row.paymentMethod?.name || "" },
              { key: "amount", label: "Amount", render: (row) => inr(row.amount), value: (row) => Number(row.amount.value) },
            ]}
          />
        ) : null}
        {!loading && account && section === "disputes" ? (
          <div className="stack">
            {disputes.length === 0 && adjustments.length === 0 ? (
              <p className="empty">No disputes. Ask the assistant if a charge looks wrong. A credit stays pending until ops approves it.</p>
            ) : null}
            {disputes.map((dispute) => (
              <article key={dispute.id} className="proposal">
                <div className="proposal-top">
                  <strong>Dispute</strong>
                  <StatusBadge status={dispute.status} />
                </div>
                <p>{dispute.description}</p>
                <p className="proposal-status">
                  Status: {dispute.status} · {when(dispute.creationDate)}
                </p>
              </article>
            ))}
            {adjustments.map((adjustment) => (
              <article key={adjustment.id} className="proposal">
                <div className="proposal-top">
                  <strong>{adjustment.adjustmentType === "credit" ? "Credit" : "Debit"}</strong>
                  <StatusBadge status={adjustment.status} />
                </div>
                <p className="proposal-amount">{inr(adjustment.amount)}</p>
                <p>{adjustment.reason}</p>
                <p className="proposal-status">
                  Status: {adjustment.status}
                  {adjustment.decidedBy ? ` · decided by ${adjustment.decidedBy}` : ""}
                </p>
              </article>
            ))}
          </div>
        ) : null}
      </section>
      <section className="chat panel" aria-label="Customer chat">
        <header className="panel-head">
          <div>
            <p className="eyebrow">Assistant</p>
            <h2>Ask about this bill</h2>
          </div>
        </header>
        <div className="prompts">
          {PROMPTS.map((prompt) => (
            <button key={prompt} type="button" className="prompt" onClick={() => send(prompt)} disabled={busy}>
              {prompt}
            </button>
          ))}
        </div>
        <div className="thread" aria-live="polite">
          {turns.length === 0 ? (
            <p className="empty">Bills, disputes, roaming, payments, and allowances. Answers cite the policy section they used.</p>
          ) : null}
          {turns.map((turn) => (
            <article key={turn.id} className={`bubble ${turn.role}`}>
              <p className="who">{turn.role === "user" ? "You" : "BillPilot"}</p>
              {turn.role === "assistant" ? (
                <AnswerText text={turn.text} onCite={(doc, sectionName) => setCitation({ doc, section: sectionName })} />
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
            </article>
          ))}
          {busy ? <p className="muted">Looking through the bill and the policy pages…</p> : null}
          {error ? <p className="error">{error}</p> : null}
        </div>
        <form
          className="composer"
          onSubmit={(event) => {
            event.preventDefault();
            void send(draft);
          }}
        >
          <label className="sr-only" htmlFor="customer-message">
            Message
          </label>
          <textarea
            id="customer-message"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder="Ask about a charge, a dispute, roaming, or a payment"
            rows={2}
          />
          <button type="submit" className="primary" disabled={busy || !draft.trim()}>
            Send
          </button>
        </form>
      </section>
      {citation ? (
        <PolicyDrawer api={api} doc={citation.doc} section={citation.section} onClose={() => setCitation(null)} />
      ) : null}
    </div>
  );
}
