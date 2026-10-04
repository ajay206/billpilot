# CSR runbooks

Synthetic steps for a care agent. Each runbook is a checklist. Cite the section you used. Do not skip the approval step.

## Double charge

Follow these numbered steps in this runbook.

1. Open the latest bill and its lines.
2. Find two lines with the same description and the same amount.
3. Open a dispute and a trouble ticket so treatment can hold.
4. Propose a credit for one of the lines, including tax, and stop.
5. Tell the customer the credit is pending review. Do not apply it.

## Barred after the bill was paid

Follow these numbered steps in this runbook.

1. Read the treatment stage and status.
2. Read posted payments against the bill that started the ladder.
3. If the posted payments cover the bill and the bar is still active, say the bar should have ended.
4. Do not unbar. Hand the service change to ops with the payment id and the treatment id.

## Allowance did not reset

Follow these numbered steps in this runbook.

1. Read the balance period and the remaining quantity.
2. Compare the period with the current bill cycle.
3. If the reset time has passed and the remaining quantity is still the previous cycle, say the allowance did not reset.
4. Do not grant units yourself. A person corrects the balance.

## Failed autopay that later posted

Follow these numbered steps in this runbook.

1. List payment attempts and payments.
2. A failed attempt followed by a posted payment is a recovery, not a missing payment.
3. Explain both timestamps. Do not propose a credit for the failed attempt when the posted payment is already on the bill.

## Failed payment

Follow these numbered steps in this runbook. The symptom token is PAYMENT_DECLINED.

1. Read payment attempts and payments for the account.
2. If the latest autopay attempt failed and no payment was posted, tell the customer the charge did not land.
3. Check for an open failed-payment or failed-autopay incident and quote its title.
4. Do not post a payment and do not propose a credit for a decline. A person retries the instrument.

## Unbar not applied

Follow these numbered steps in this runbook.

1. Read the treatment stage, status, and hold reason.
2. Read posted payments against the bill that started the ladder.
3. If the bill is paid and the bar is still active, say the unbar was not applied.
4. Do not unbar the line. Hand the service change to ops with the payment and the treatment id.

## Roaming not working

Follow these numbered steps in this runbook.

1. Read the entitlement products and the allowance balances.
2. Check whether a roaming pack is still pending activation.
3. If the pack was charged and the entitlement is missing or pending, say roaming was not provisioned.
4. Do not activate the pack yourself. Open the evidence for ops.

## Bill not generated

Follow these numbered steps in this runbook.

1. Read the latest bills and their issue dates.
2. If the expected cycle has no bill, say the bill was not generated.
3. Look for a stuck or failed bill-run incident on the account.
4. Do not create an invoice. Ops reruns the bill.

## Entitlement missing

Follow these numbered steps in this runbook.

1. Read entitlement products and allowance balances.
2. Compare the active products with the plan the subscription is on.
3. If the plan includes the feature and the product is missing, say the entitlement is missing.
4. Do not grant units. A person corrects the balance.

## How to propose a credit

1. Use only amounts you read from the bill, the offering, or a cited section.
2. Propose a credit. Leave the status pending approval.
3. Never call an approve or apply action. Ops uses the existing approval endpoint, and the proposer cannot be the approver.
