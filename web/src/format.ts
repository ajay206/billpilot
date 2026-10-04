import type { Money } from "./types";

export function inr(amount: Money | string | null | undefined): string {
  const raw = typeof amount === "string" ? amount : amount?.value;
  if (!raw) return "—";
  const value = Number(raw);
  if (Number.isNaN(value)) return `₹${raw}`;
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

export function when(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso.slice(0, 10);
  return new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric" }).format(date);
}

export function whenTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso.slice(0, 16);
  return new Intl.DateTimeFormat("en-IN", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function partyName(parties: { name?: string | null }[] | undefined): string {
  return parties?.find((party) => party.name)?.name || "Account";
}

export function actorLabel(actor: string | null | undefined): string {
  if (!actor) return "unknown";
  const split = actor.indexOf(":");
  if (split === -1) return actor;
  const kind = actor.slice(0, split);
  const rest = actor.slice(split + 1);
  if (kind === "user" || kind === "csr" || kind === "customer" || kind === "ops") return rest || kind;
  return actor;
}

export function characteristic(rows: { name: string; value: string }[] | undefined, name: string): string {
  return rows?.find((row) => row.name === name)?.value ?? "";
}
