import { useState } from "react";

import type { Api } from "../../../api";
import { AnswerText } from "../../../components";

type Incident = { id: string; title: string; incidentType: string; severity: string; status: string };

type TroubleshootResult = {
  answer: string;
  refusal: boolean;
  toolCalls: { name: string }[];
  relatedIncidents: Incident[];
};

const SAMPLES = [
  "Troubleshooting: a payment failed with token PAYMENT_DECLINED. Follow the failed payment runbook.",
  "Troubleshooting: the unbar was not applied after payment. Do not unbar the line.",
  "Troubleshooting: roaming not working after a pack was added. Follow the roaming runbook.",
  "Troubleshooting: the bill not generated for this cycle. Follow the bill runbook.",
  "Troubleshooting: entitlement missing on the subscription. Follow the entitlement runbook.",
];

export function TroubleshootPanel({ api, accountId }: { api: Api; accountId: string | null }) {
  const [message, setMessage] = useState(SAMPLES[0]);
  const [result, setResult] = useState<TroubleshootResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run() {
    if (!accountId) {
      setError("Select an account first.");
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

  return (
    <section className="phase4-panel" aria-label="CSR troubleshooting">
      <h3>CSR troubleshooting</h3>
      <p className="phase4-meta">
        Paste an error or describe a symptom. The assistant returns numbered runbook steps, checks this account, and lists related incidents.
      </p>
      <div className="phase4-samples">
        {SAMPLES.map((sample) => (
          <button key={sample} className="ghost" type="button" onClick={() => setMessage(sample)}>
            {sample.replace("Troubleshooting: ", "").slice(0, 42)}
          </button>
        ))}
      </div>
      <label htmlFor="trouble-message">Error or symptom</label>
      <textarea id="trouble-message" rows={3} value={message} onChange={(event) => setMessage(event.target.value)} />
      <button className="primary" type="button" onClick={run} disabled={busy || !accountId}>
        Run troubleshooting
      </button>
      {!accountId ? <p className="phase4-meta">Select an account to run the steps.</p> : null}
      {error ? <p className="error">{error}</p> : null}
      {result ? (
        <div>
          <div className="phase4-answer">
            <AnswerText text={result.answer} onCite={() => undefined} />
          </div>
          <p className="phase4-meta">Tools: {result.toolCalls.map((call) => call.name).join(", ") || "none"}</p>
          <h4>Related incidents</h4>
          {result.relatedIncidents.length === 0 ? <p className="empty">No related incidents on this account.</p> : null}
          <ul className="phase4-list">
            {result.relatedIncidents.map((incident) => (
              <li key={incident.id}>
                <strong>{incident.title}</strong>
                <div className="phase4-meta">
                  {incident.incidentType} · {incident.severity} · {incident.status}
                </div>
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
