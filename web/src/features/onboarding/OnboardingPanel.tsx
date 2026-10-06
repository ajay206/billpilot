import { useState } from "react";
import type { FormEvent } from "react";

import { ApiError } from "../../api";
import type { Api } from "../../api";
import { formatINR } from "../../format";

type Preview = {
  posted: boolean;
  subtotal: string;
  tax: string;
  total: string;
  dueDate: string;
  lines: { description: string; chargeType: string; amount: string }[];
};

type Onboarded = {
  customerNumber: string;
  accountNumber: string;
  msisdn: string;
  planName: string;
  treatmentStage: string;
  treatmentStatus: string;
  creditClass: string;
  creditLimit: string;
  entitlements: { feature: string; allowance: string; unit: string; status: string }[];
  vas: string[];
  welcomeMessage: string;
  firstBillPreview: Preview;
};

const PLANS = [
  ["SMART-199", "Smart 199"],
  ["PLUS-399", "Plus 399"],
  ["MAX-599", "Max 599"],
  ["ULTRA-999", "Ultra 999"],
] as const;

export function OnboardingPanel({ api }: { api: Api }) {
  const [givenName, setGivenName] = useState("Asha");
  const [familyName, setFamilyName] = useState("Iyer");
  const [email, setEmail] = useState("");
  const [phone, setPhone] = useState("+919800000001");
  const [city, setCity] = useState("Pune");
  const [stateName, setStateName] = useState("Maharashtra");
  const [msisdn, setMsisdn] = useState("");
  const [planCode, setPlanCode] = useState("PLUS-399");
  const [callerTune, setCallerTune] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Onboarded | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const response = await api.post<Onboarded>("/onboarding", {
        givenName,
        familyName,
        email,
        phone,
        city,
        state: stateName,
        msisdn,
        planCode,
        billingCycleDay: 1,
        optedInVas: callerTune ? ["CALLER-TUNE"] : [],
      });
      setResult(response.data);
    } catch (reason) {
      setResult(null);
      setError(reason instanceof ApiError ? reason.message : "Onboarding did not complete.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="phase5" aria-label="Onboarding">
      <p className="eyebrow">Onboarding</p>
      <h3>Onboard a customer</h3>
      <p className="muted">
        One call creates the customer, account, and subscription, provisions plan entitlements and any opted-in VAS, and
        sets treatment to none with a new credit profile. The first bill is a preview and is not posted.
      </p>
      <form className="phase5-grid" onSubmit={(event) => void submit(event)}>
        <label>
          Given name
          <input value={givenName} onChange={(event) => setGivenName(event.target.value)} required />
        </label>
        <label>
          Family name
          <input value={familyName} onChange={(event) => setFamilyName(event.target.value)} required />
        </label>
        <label>
          Email
          <input type="email" value={email} onChange={(event) => setEmail(event.target.value)} required />
        </label>
        <label>
          Phone
          <input value={phone} onChange={(event) => setPhone(event.target.value)} required />
        </label>
        <label>
          City
          <input value={city} onChange={(event) => setCity(event.target.value)} required />
        </label>
        <label>
          State
          <input value={stateName} onChange={(event) => setStateName(event.target.value)} required />
        </label>
        <label>
          MSISDN
          <input value={msisdn} onChange={(event) => setMsisdn(event.target.value)} inputMode="numeric" required />
        </label>
        <label>
          Plan
          <select value={planCode} onChange={(event) => setPlanCode(event.target.value)}>
            {PLANS.map(([code, name]) => (
              <option key={code} value={code}>
                {name}
              </option>
            ))}
          </select>
        </label>
        <label className="checks">
          <input type="checkbox" checked={callerTune} onChange={(event) => setCallerTune(event.target.checked)} />
          Opt in to caller tune
        </label>
        <div className="phase5-actions">
          <button type="submit" className="primary" disabled={busy}>
            {busy ? "Opening…" : "Create customer"}
          </button>
        </div>
      </form>
      {error ? <p className="error">{error}</p> : null}
      {result ? (
        <div className="welcome" aria-live="polite">
          <p>{result.welcomeMessage}</p>
          <p className="muted">
            {result.customerNumber} · {result.accountNumber} · {result.msisdn} · {result.planName}
          </p>
          <p className="muted">
            Treatment {result.treatmentStage} ({result.treatmentStatus}) · Credit {result.creditClass} · limit{" "}
            {formatINR(result.creditLimit)}
          </p>
          <ul>
            {result.entitlements.map((row) => (
              <li key={row.feature}>
                {row.feature}: {row.allowance} {row.unit} ({row.status})
              </li>
            ))}
          </ul>
          {result.vas.length ? <p>Opted-in VAS: {result.vas.join(", ")}</p> : <p>No VAS opted in.</p>}
          <h4>First bill preview · {formatINR(result.firstBillPreview.total)}</h4>
          <p className="muted">Not posted. Due {result.firstBillPreview.dueDate}.</p>
          <ul>
            {result.firstBillPreview.lines.map((line) => (
              <li key={line.description}>
                {line.description}: {formatINR(line.amount)}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
