export type PersonaId = "customer" | "csr" | "ops";

/** Published local demo keys. They are not credentials for a real system. */
export const PERSONAS: { id: PersonaId; label: string; key: string; scope: string }[] = [
  { id: "customer", label: "Customer", key: "dev-customer-key", scope: "Own account" },
  { id: "csr", label: "CSR", key: "dev-csr-key", scope: "Assigned accounts" },
  { id: "ops", label: "Ops", key: "dev-ops-key", scope: "Approvals and audit" },
];

export function personaById(id: PersonaId) {
  return PERSONAS.find((persona) => persona.id === id) ?? PERSONAS[0];
}

export function personaPath(id: PersonaId): string {
  return `/${id}`;
}

/** `/` is the customer view. `/csr` and `/ops` are the other two. */
export function personaFromPath(path: string): PersonaId {
  const head = path.split("/").filter(Boolean)[0];
  if (head === "csr" || head === "ops") return head;
  return "customer";
}
