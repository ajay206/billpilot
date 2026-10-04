import { useEffect, useState } from "react";

import type { Api } from "../api";
import { qs } from "../api";
import { AnswerText, PolicyDrawer, ProposalCard, StatusBadge } from "../components";
import { inr, partyName, when } from "../format";
import type { Account, Adjustment, Bill, ChatResponse, Citation, Dispute, Proposed, ToolCall } from "../types";

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

export function CustomerChat({ api }: { api: Api }) {
  const [account, setAccount] = useState<Account | null>(null);
  const [bills, setBills] = useState<Bill[]>([]);
  const [disputes, setDisputes] = useState<Dispute[]>([]);
  const [adjustments, setAdjustments] = useState<Adjustment[]>([]);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [citation, setCitation] = useState<{ doc: string; section: string } | null>(null);

  async function loadAccount(current: Api) {
    const accounts = await current.get<Account[]>(qs("/tmf-api/accountManagement/v4/billingAccount", { limit: 5 }));
    const next = accounts.data[0] ?? null;
    setAccount(next);
    if (!next) return;
    const [billRows, disputeRows, adjustmentRows] = await Promise.all([
      current.get<Bill[]>(qs("/tmf-api/customerBillManagement/v4/customerBill", { "billingAccount.id": next.id, limit: 4 })),
      current.get<Dispute[]>(
        qs("/tmf-api/customerBillManagement/v4/customerBillDispute", { "billingAccount.id": next.id, limit: 8 }),
      ),
      current.get<Adjustment[]>(
        qs("/tmf-api/customerBillManagement/v4/billAdjustment", { "billingAccount.id": next.id, limit: 8 }),
      ),
    ]);
    setBills(billRows.data);
    setDisputes(disputeRows.data);
    setAdjustments(adjustmentRows.data);
  }

  useEffect(() => {
    let cancel = false;
    loadAccount(api).catch((reason: Error) => {
      if (!cancel) setError(reason.message);
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
      const result = await api.post<ChatResponse>("/agent/chat", {
        message,
        accountId: account?.id,
      });
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
      const messageText = reason instanceof Error ? reason.message : "The copilot did not answer.";
      setError(messageText);
    } finally {
      setBusy(false);
    }
  }

  const name = account ? partyName(account.relatedParty) : "Demo customer";

  return (
    <div className="split">
      <section className="chat" aria-label="Customer chat">
        <header className="panel-head">
          <div>
            <p className="eyebrow">Customer assistant</p>
            <h2>Ask about this bill</h2>
          </div>
          <p className="signed-in">Signed in as {name}</p>
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
              {turn.role === "assistant" ? <AnswerText text={turn.text} onCite={(doc, section) => setCitation({ doc, section })} /> : <p>{turn.text}</p>}
              {turn.proposed?.map((item) => (
                <ProposalCard key={`${item.type}-${item.id}`} item={item} />
              ))}
              {turn.citations && turn.citations.length > 0 ? (
                <div className="cite-row">
                  {turn.citations.map((item) => (
                    <button
                      key={`${item.doc}-${item.section}`}
                      type="button"
                      className="cite"
                      onClick={() => setCitation(item)}
                    >
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
      <aside className="rail" aria-label="Account status">
        <p className="eyebrow">This account</p>
        <h2>{name}</h2>
        <p className="muted">
          {account ? `${account.customerNumber} · ${account.name}` : "Loading the demo account…"}
        </p>
        {bills[0] ? (
          <div className="bill-chip">
            <span>Latest bill {bills[0].billNo}</span>
            <strong>{inr(bills[0].taxIncludedAmount)}</strong>
            <span>Due {inr(bills[0].amountDue)}</span>
          </div>
        ) : null}
        <h3>Disputes and credits</h3>
        {disputes.length === 0 && adjustments.length === 0 ? (
          <p className="empty">Nothing is waiting on review.</p>
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
      </aside>
      {citation ? (
        <PolicyDrawer api={api} doc={citation.doc} section={citation.section} onClose={() => setCitation(null)} />
      ) : null}
    </div>
  );
}
