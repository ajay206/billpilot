export type Money = { unit: string; value: string };

export type Party = { id: string; role: string; name?: string | null };

export type Account = {
  id: string;
  name: string;
  customerNumber: string;
  state: string;
  treatment?: { stage: string; status: string; holdReason?: string | null; startedAt: string } | null;
  exemption?: { reason: string } | null;
  relatedParty: Party[];
};

export type Bill = {
  id: string;
  billNo: string;
  billDate: string;
  state: string;
  taxIncludedAmount: Money;
  amountDue: Money;
};

export type Rate = {
  id: string;
  name: string;
  appliedBillingRateType: string;
  taxExcludedAmount: Money;
  bill?: { id: string; name?: string | null } | null;
};

export type Usage = {
  id: string;
  usageDate: string;
  description: string;
  usageType: string;
  usageCharacteristic: { name: string; value: string }[];
};

export type Payment = {
  id: string;
  paymentDate: string;
  status: string;
  amount: Money;
  paymentMethod?: { name?: string };
};

export type Dispute = {
  id: string;
  description: string;
  category: string;
  status: string;
  creationDate: string;
};

export type Adjustment = {
  id: string;
  adjustmentType: string;
  status: string;
  reason: string;
  amount: Money;
  creationDate: string;
  proposedBy: string;
  decidedBy?: string | null;
  billingAccount: { id: string; name?: string | null };
};

export type Ticket = {
  id: string;
  name: string;
  status: string;
  severity: string;
  creationDate: string;
};

export type FraudFlag = {
  id: string;
  flagType: string;
  severity: string;
  status: string;
  detectedAt: string;
};

export type Citation = { doc: string; section: string };

export type ToolCall = {
  name: string;
  arguments?: Record<string, unknown>;
  ok: boolean;
  status: number | null;
  preview?: string;
};

export type Proposed = {
  type?: string;
  id?: string;
  status?: string;
  amount?: string;
};

export type ChatResponse = {
  runId: string;
  answer: string;
  refusal: boolean;
  refusalReason: string | null;
  grounded: boolean;
  citations: Citation[];
  proposedActions: Proposed[];
  toolCalls: ToolCall[];
  promptTokens: number;
  completionTokens: number;
  estimatedCostUsd: string;
  latencyMs: number;
  model: string;
  traceId: string | null;
};

export type AgentRun = {
  id: string;
  occurredAt: string;
  persona: string;
  actorId: string;
  userMessage: string;
  decision: string;
  promptTokens: number;
  completionTokens: number;
  estimatedCostUsd: string;
  latencyMs: number;
  model: string;
  traceId: string | null;
  refusal: boolean;
};

export type AuditEntry = {
  id: string;
  occurredAt: string;
  actorRole: string;
  actorId: string;
  action: string;
  resourceType: string;
  resourceId: string;
  requestId: string;
};

export type PolicySection = {
  doc: string;
  title: string;
  section: string;
  source: string;
  body: string;
};

export type Health = {
  status: string;
  demoMode: boolean;
  llmBackend: string;
  tracing: boolean;
};
