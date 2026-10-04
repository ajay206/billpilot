# Billing policy

Synthetic policy for the BillPilot learning mock. Currency is INR. One bill covers one account and one cycle.

## How a bill is calculated

A bill lists recurring charges, usage, roaming, value-added services, discounts, a late fee when one applies, and one tax line. The lines are signed, so they add up to the total. Amount due is the total minus posted payments, and it is never negative. Compare a bill with the previous month by reading both totals and the lines that changed: a higher total usually means extra usage, roaming, a missing discount, or a duplicate line.

## Goods and services tax

Goods and services tax on this mock is a single line at 18 percent of the pre-tax subtotal. It is not split into CGST and SGST. A non-positive subtotal is not taxed. Quoting the rate without the bill in front of you is fine; quoting a customer's tax amount requires the bill.

## Late fee

An unpaid bill whose due date is already past carries a flat late fee of 50.00 INR, plus tax on the new subtotal. The fee is one line. It is not a percentage of the balance. A payment that posts on time does not get this fee.

## Partial months and plan changes

If a subscription ends during a cycle, recurring charges for the days after the end should not stay on the bill. This mock's planted examples make that fault visible as a charge after cancellation. Explain the rental, the end date, and the days that should not have been billed. Do not invent a daily rate that is not on the tariff.

## Reading a line

Each line has a description, a type (recurring, usage, roaming, discount, tax, late fee, adjustment), a quantity, a unit price, and an amount. Two lines with the same description and the same amount on one bill are a duplicate until a person shows they are two different products.
