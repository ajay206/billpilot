import { useState } from "react";

import type { Api } from "../../../api";
import { AnswerText, SeverityBadge, StatusBadge } from "../../../components";

type Incident = { id: string; title: string; incidentType: string; severity: string; status: string };

type ToolCall = { name: string; ok?: boolean; summary?: string };

type TroubleshootResult = {
  answer: string;
  refusal: boolean;
  toolCalls: ToolCall[];
  citations?: { doc: string; section: string }[];
  relatedIncidents: Incident[];
};

const SAMPLES = [
  {
    label: "Payment declined",
    message: "Troubleshooting: a payment failed with token PAYMENT_DECLINED. Follow the failed payment runbook.",
  },
  {
    label: "Unbar not applied",
    message: "Troubleshooting: the unbar was not applied after payment. Do not unbar the line.",
  },
  {
    label: "Roaming not working",
    message: "Troubleshooting: roaming not working after a pack was added. Follow the roaming runbook.",
  },
  {
    label: "Bill not generated",
    message: "Troubleshooting: the bill not generated for this cycle. Follow the bill runbook.",
  },
  {
    label: "Entitlement missing",
    message: "Troubleshooting: entitlement missing on the subscription. Follow the entitlement runbook.",
  },
];

function numberedSteps(text: string): string[] | null {
  const matches = [...text.matchAll(/(?:^|\n)\s*\d+\.\s+([\s\S]*?)(?=\n\s*\d+\.\s+|$)/g)];
  if (matches.length < 2) return null;
  return matches.map((match) => match[1].trim()).filter(Boolean);
}

function presentAnswer(text: string): { lead: string; steps: string[] | null; body: string } {
  const body = text.replace(/\nRelated incidents:[\s\S]*$/i, "").trim();
  const steps = numberedSteps(body);
  const lead = steps ? (body.match(/^([\s\S]*?)(?=\n\s*1\.\s+)/)?.[1] ?? "").trim() : "";
  return { lead, steps, body };
}

function checkLabel(name: string): string {
  return name.replaceAll("_", " ");
}

export function TroubleshootPanel({
  api,
  accountId,
  onCite,
}: {
  api: Api;
  accountId: string | null;
  onCite?: (doc: string, section: string) => void;
}) {
  const [message, setMessage] = useState(SAMPLES[0].message);
  const [result, setResult] = useState<TroubleshootResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run() {
    if (!accountId) {
      setError("Search for an account first. Troubleshooting reads that account and does not run without one.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const response = await api.post<TroubleshootResult>("/agent/troubleshoot", { accountId, message });
      setResult(response.data);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Troubleshooting failed.");
    } finally {
      setBusy(false);
    }
  }

  const presented = result ? presentAnswer(result.answer) : null;

  return (
    <section className="troubleshoot" aria-label="CSR troubleshooting">
      <h2>Troubleshooting</h2>
      <p className="muted">
        Paste an error or describe a symptom. The assistant returns numbered runbook steps, checks this account, and lists related incidents.
      </p>
      <div className="tabs" role="list" aria-label="Sample symptoms">
        {SAMPLES.map((sample) => (
          <button
            key={sample.label}
            className={message === sample.message ? "tab selected" : "tab"}
            type="button"
            onClick={() => setMessage(sample.message)}
          >
            {sample.label}
          </button>
        ))}
      </div>
      <label className="field" htmlFor="trouble-message">
        Error or symptom
        <textarea id="trouble-message" rows={5} value={message} onChange={(event) => setMessage(event.target.value)} />
      </label>
      <button className="primary" type="button" onClick={() => void run()} disabled={busy || !accountId}>
        {busy ? "Reading the account…" : "Run troubleshooting"}
      </button>
      {!accountId ? <p className="empty">Search for an account to run troubleshooting.</p> : null}
      {accountId && busy ? <p className="muted">Checking the account and the runbooks.</p> : null}
      {error ? (
        <p className="error" role="alert">
          {error}
        </p>
      ) : null}
      {result ? (
        <div className="stack">
          {result.refusal ? <p className="notice">The assistant refused this request.</p> : null}
          {presented?.lead ? <p>{presented.lead}</p> : null}
          {presented?.steps ? (
            <ol className="runbook-steps">
              {presented.steps.map((step) => (
                <li key={step}>
                  <AnswerText text={step} onCite={onCite ?? (() => undefined)} />
                </li>
              ))}
            </ol>
          ) : (
            <AnswerText text={presented?.body || result.answer} onCite={onCite ?? (() => undefined)} />
          )}
          <h3>Account checks</h3>
          {result.toolCalls.length === 0 ? <p className="empty">No account checks were run.</p> : null}
          {result.toolCalls.length > 0 ? (
            <ul className="check-list">
              {result.toolCalls.map((call, index) => (
                <li key={`${call.name}-${index}`}>
                  <strong>{checkLabel(call.name)}</strong>
                  <span className={call.ok === false ? "bad-text" : "ok"}>{call.ok === false ? "failed" : "ok"}</span>
                  <p className="muted">{call.summary || "No readable result."}</p>
                </li>
              ))}
            </ul>
          ) : null}
          <h3>Related incidents</h3>
          {result.relatedIncidents.length === 0 ? <p className="empty">No related incidents on this account.</p> : null}
          {result.relatedIncidents.length > 0 ? (
            <ul className="check-list">
              {result.relatedIncidents.map((incident) => (
                <li key={incident.id}>
                  <strong>{incident.title}</strong>
                  <SeverityBadge severity={incident.severity} />
                  <StatusBadge status={incident.status} />
                  <span className="muted">{incident.incidentType.replaceAll("_", " ")}</span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
