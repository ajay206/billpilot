# Refunds and credits

Synthetic rules for money leaving a bill. The copilot proposes. A different person approves.

## Credit versus a cash refund

A credit reduces the bill total. It is not a cash refund and it does not return money to a bank account. Crediting an already-paid bill can leave amount due at zero. It still does not create a payout. Say "credit" unless the customer asked about a deposit refund, which is a different page.

## Who proposes and who approves

A CSR proposes a credit or a debit. The proposal is stored as pending approval and does not change the invoice. An ops person approves or rejects it on the adjustment approval endpoint. The proposer cannot approve their own proposal. The copilot may propose a credit. It must never apply one, and it has no approve tool. Tell the customer the credit is pending review.

## Duplicate charges

If the latest invoice has two identical recurring lines, credit one of them, including the tax that was charged on it. Propose that credit with the bill id and a short reason. Leave the status pending. Do not delete the line yourself.

## Wrong rate and missed discount

A usage line priced above the catalogue rate is a wrong-rate fault. Credit the difference, including tax. A subscription with a loyalty discount and no discount line on the latest bill is a missed discount. Credit the missed discount, including tax. Read the discount percent from the product, not from a guess.

## Charge after cancellation

Usage or rental after the subscription end time should not be billed. Credit the charges that fall after cancellation. Confirm the end time on the product before proposing the amount.

## The tax line stays put

When a credit is applied, this mock does not recompute the tax line. The adjustment is a signed line so the lines still sum to the new total. Propose one credit amount. Do not also propose a separate tax adjustment.
