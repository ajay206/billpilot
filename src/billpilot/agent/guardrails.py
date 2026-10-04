"""Input and output checks for the copilot.

Refusals happen before the model is called. Tool text is treated as data:
instructions hidden inside a bill or a document are stripped before the model
sees them. Amounts in the answer have to appear in tool results or cited text.
"""

import re
from decimal import Decimal, InvalidOperation

CITATION_RE = re.compile(r"\[([A-Za-z0-9._-]+\.md) § ([^\[\]\n]+?)\]")
AMOUNT_RE = re.compile(r"\d+\.\d{2}")
CUSTOMER_RE = re.compile(r"CUST-\d{6}", re.IGNORECASE)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"\+91\d{10}")

_INJECTION = re.compile(
    r"("
    r"ignore (all |any |the )?(previous |prior |above )?instructions"
    r"|disregard (the |your )?(system |previous )?"
    r"|system prompt"
    r"|developer message"
    r"|you are now"
    r"|reveal (the |your )?(api key|secret|prompt|instructions)"
    r"|<\s*/?\s*system\s*>"
    r")",
    re.IGNORECASE,
)

_OUT_OF_SCOPE = re.compile(
    r"("
    r"\bweather\b"
    r"|\bpoem\b"
    r"|\bjoke\b"
    r"|\brecipe\b"
    r"|\bstock price\b"
    r"|write (me )?(some )?(python |java )?code"
    r"|every customer"
    r"|all customers"
    r"|dump (the |all )?(accounts|customers)"
    r")",
    re.IGNORECASE,
)

# Money and service changes stay with a person. "Do not apply" is not a request to apply.
_UNAUTHORIZED = re.compile(
    r"("
    r"\bapply (the |this |my )?(credit|adjustment|refund)\b"
    r"|\bapprove (the |this |that )?(adjustment|credit|refund)\b"
    r"|\bdisconnect (the |this |my )?(line|service|account)\b"
    r"|\bunbar\b"
    r"|\bremove the bar\b"
    r"|\bchange (my |the )plan\b"
    r"|\bcall the approve\b"
    r")",
    re.IGNORECASE,
)

_DO_NOT = re.compile(r"\b(do not|don't|never|do not post|leave it pending)\b", re.IGNORECASE)

# Committing or rolling back a migration writes the ledger. The copilot may only read a batch.
_MIGRATION_WRITE = re.compile(
    r"("
    r"\bcommit the migration\b"
    r"|\broll back the (migration|batch)\b"
    r"|\brollback the (migration|batch)\b"
    r"|\bsign off (on )?the (mapping|migration|batch)\b"
    r"|\bapprove the (mapping|migration)\b"
    r"|\brun the migration\b"
    r")",
    re.IGNORECASE,
)
_MIGRATION_READ = re.compile(r"\bmigration batch\b|\bmigration rejects\b|\blegacy file\b", re.IGNORECASE)


def format_citation(doc: str, section: str) -> str:
    return f"[{doc} § {section}]"


def citations_in(text: str) -> list[dict[str, str]]:
    return [{"doc": doc.strip(), "section": section.strip()} for doc, section in CITATION_RE.findall(text)]


def dedupe_citations(items: list[dict[str, str]]) -> list[dict[str, str]]:
    """One entry per document and section, in first-seen order."""
    unique: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        doc = (item.get("doc") or "").strip()
        section = (item.get("section") or "").strip()
        key = (doc, section)
        if not doc or not section or key in seen:
            continue
        seen.add(key)
        unique.append({"doc": doc, "section": section})
    return unique


def collapse_duplicate_citations(answer: str) -> str:
    """Drop a repeated [doc § section] marker. The first one stays."""
    seen: set[tuple[str, str]] = set()

    def replace(match: re.Match[str]) -> str:
        key = (match.group(1).strip(), match.group(2).strip())
        if key in seen:
            return ""
        seen.add(key)
        return match.group(0)

    collapsed = CITATION_RE.sub(replace, answer)
    collapsed = re.sub(r"[ \t]{2,}", " ", collapsed)
    return collapsed.strip()


def screen_input(message: str, persona: str, customer_number: str | None) -> str | None:
    """Return a refusal reason, or None when the message may go to the model."""
    text = message.strip()
    if not text:
        return "empty"
    if len(text) > 4000:
        return "too_long"
    if _INJECTION.search(text):
        return "prompt_injection"
    if persona != "ops" and _MIGRATION_READ.search(text):
        return "out_of_scope"
    if _OUT_OF_SCOPE.search(text):
        return "out_of_scope"
    if (_UNAUTHORIZED.search(text) or _MIGRATION_WRITE.search(text)) and not _DO_NOT.search(text):
        return "needs_a_person"
    if persona == "customer" and customer_number:
        others = [number.upper() for number in CUSTOMER_RE.findall(text) if number.upper() != customer_number.upper()]
        if others:
            return "cross_account"
    return None


def refusal_message(reason: str) -> str:
    return {
        "empty": "Ask a billing question and I will look it up.",
        "too_long": "That message is too long. Ask about one bill, dispute, or policy.",
        "prompt_injection": "I can't follow instructions that try to change my role or reveal secrets.",
        "out_of_scope": "I only help with this account's bills, usage, payments, treatment, and published policy.",
        "needs_a_person": (
            "I can investigate and propose a credit, but I cannot apply a credit, approve one, "
            "unbar a line, or change a plan. A person does that on the approval endpoint."
        ),
        "cross_account": "I can only see the account this login is allowed to see.",
        "tool_budget": "I stopped because this turn reached its tool-call budget.",
        "token_budget": "I stopped because this turn reached its token budget.",
        "no_account": "This login has no billing account I am allowed to read.",
    }.get(reason, "I can't help with that request.")


def sanitize_untrusted(text: str) -> str:
    """Remove instruction-shaped phrases from tool and document text."""
    return _INJECTION.sub("[removed untrusted instruction]", text)


def redact_secrets(text: str, secrets: list[str]) -> str:
    for secret in secrets:
        if secret and len(secret) >= 4 and secret in text:
            text = text.replace(secret, "[redacted]")
    return text


def allowed_identifiers(
    evidence: list[str], persona: str, customer_number: str | None
) -> tuple[set[str], set[str], set[str]]:
    blob = "\n".join(evidence)
    customers = {number.upper() for number in CUSTOMER_RE.findall(blob)}
    emails = {email.lower() for email in EMAIL_RE.findall(blob)}
    phones = set(PHONE_RE.findall(blob))
    if persona == "customer" and customer_number:
        customers = {customer_number.upper()}
    return customers, emails, phones


def redact_pii(answer: str, customers: set[str], emails: set[str], phones: set[str]) -> tuple[str, bool]:
    """Replace identifiers that never appeared in this turn's scoped evidence."""
    changed = False

    def customer(match: re.Match[str]) -> str:
        nonlocal changed
        if match.group(0).upper() in customers:
            return match.group(0)
        changed = True
        return "[redacted]"

    def email(match: re.Match[str]) -> str:
        nonlocal changed
        if match.group(0).lower() in emails:
            return match.group(0)
        changed = True
        return "[redacted]"

    def phone(match: re.Match[str]) -> str:
        nonlocal changed
        if match.group(0) in phones:
            return match.group(0)
        changed = True
        return "[redacted]"

    answer = CUSTOMER_RE.sub(customer, answer)
    answer = EMAIL_RE.sub(email, answer)
    answer = PHONE_RE.sub(phone, answer)
    return answer, changed


def _amounts(text: str) -> set[str]:
    return set(AMOUNT_RE.findall(text))


def screen_output(
    answer: str,
    evidence: list[str],
    retrieved: list[dict[str, str]],
    user_message: str = "",
) -> tuple[str, bool, list[dict[str, str]]]:
    """Keep citations that match retrieved sections, and amounts that were retrieved.

    Advise-tier answers (an explanation, a policy answer, plan advice, a
    runbook) have to cite a section that search actually returned. A failed
    check replaces the answer. The model does not get a second chance in the
    same turn: an ungrounded amount is not shown.
    """
    answer = collapse_duplicate_citations(answer)
    trusted: list[dict[str, str]] = []
    known = {(item["doc"], item["section"]) for item in retrieved}
    seen: set[tuple[str, str]] = set()
    for citation in citations_in(answer):
        key = (citation["doc"], citation["section"])
        if key in known and key not in seen:
            trusted.append(citation)
            seen.add(key)
    trusted = dedupe_citations(trusted)
    invented = [citation for citation in citations_in(answer) if (citation["doc"], citation["section"]) not in known]
    evidence_text = "\n".join(evidence)
    missing_amounts = sorted(_amounts(answer) - _amounts(evidence_text))
    searched = any(item.get("doc") for item in retrieved)
    cited_without_search = bool(citations_in(answer)) and not searched
    if invented or missing_amounts or cited_without_search or (searched and citations_in(answer) and not trusted):
        return (
            "I can't support that from the records and policy sections I retrieved. "
            "A specialist should check the bill before any credit is proposed.",
            False,
            trusted,
        )
    if not trusted and (searched or _needs_citation(user_message)):
        return (
            "I don't have a policy section to cite for that. I will not guess.",
            False,
            [],
        )
    return answer, True, trusted


def _needs_citation(message: str) -> bool:
    """Explanations and policy answers are the advise tier. They need a source."""
    lowered = message.lower()
    markers = (
        "policy",
        "runbook",
        "cite",
        "tariff",
        "rule",
        "roaming",
        "refund",
        "deposit",
        "porting",
        "why is",
        "explain",
    )
    return any(marker in lowered for marker in markers)


def proposal_error(actions: list[dict]) -> str | None:
    """A credit proposal has to be a pending row with a positive amount.

    Anything else is not a valid change-tier action. The copilot still has
    no approve tool; this only checks the shape of what propose returned.
    """
    for action in actions:
        if action.get("type") != "credit":
            continue
        if action.get("applied") or action.get("status") != "pending_approval":
            return "needs_a_person"
        if not action.get("id"):
            return "needs_a_person"
        try:
            if Decimal(str(action.get("amount"))) <= 0:
                return "needs_a_person"
        except (InvalidOperation, ValueError):
            return "needs_a_person"
    return None
