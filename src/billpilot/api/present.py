"""Map billing rows to TMF-shaped resources.

The database keeps an internal vocabulary (issued, posted, soft_bar). The API
translates that into the smaller TMF-like vocabulary documented in the README.
Signed amounts stay signed so a reader can add the lines up to the bill total.
"""

from fastapi import Request
from sqlalchemy.orm import Session

from billpilot.api.schemas import (
    AppliedRate,
    AuditEntry,
    BillAdjustment,
    BillingAccount,
    Bucket,
    BucketCounter,
    Characteristic,
    CustomerBill,
    CustomerBillDispute,
    ExemptionState,
    FraudFlagView,
    Money,
    Payment,
    PaymentAttempt,
    Product,
    ProductOffering,
    ProductOfferingPrice,
    Quantity,
    Ref,
    RelatedParty,
    TimePeriod,
    TreatmentState,
    TroubleTicket,
    Usage,
)
from billpilot.models import (
    Account,
    AccountTreatment,
    Adjustment,
    AuditLog,
    Customer,
    Dispute,
    Entitlement,
    EntitlementBalance,
    FraudFlag,
    Invoice,
    InvoiceLine,
    Subscription,
    TariffPlan,
    Ticket,
    TreatmentExemption,
    UsageEvent,
    VasSubscription,
)
from billpilot.models import (
    Payment as PaymentRow,
)
from billpilot.models import (
    PaymentAttempt as PaymentAttemptRow,
)

_RATE_TYPE = {
    "recurring": "recurringCharge",
    "usage": "usageCharge",
    "roaming": "usageCharge",
    "vas": "recurringCharge",
    "addon": "oneTimeCharge",
    "discount": "discount",
    "adjustment": "adjustment",
    "tax": "tax",
    "late_fee": "oneTimeCharge",
}

_BILL_STATE = {
    "paid": "settled",
    "partially_paid": "partiallyPaid",
    "issued": "sent",
    "cancelled": "cancelled",
}

_PAYMENT_STATE = {
    "posted": "done",
    "received": "pending",
    "failed": "failed",
    "reversed": "declined",
}

_PRODUCT_STATUS = {
    "active": "active",
    "suspended": "suspended",
    "cancelled": "terminated",
    "expired": "terminated",
    "pending_activation": "created",
}

_TICKET_STATUS = {
    "open": "acknowledged",
    "in_progress": "inProgress",
    "resolved": "resolved",
    "closed": "closed",
}


def resource_href(request: Request, suffix: str) -> str:
    return f"{str(request.base_url).rstrip('/')}/tmf-api/{suffix}"


def ref(request: Request, suffix: str, name: str | None = None) -> Ref:
    return Ref(id=suffix.rsplit("/", 1)[-1], href=resource_href(request, suffix), name=name)


def money(amount) -> Money:
    return Money(unit="INR", value=amount)


def _party(customer: Customer) -> RelatedParty:
    return RelatedParty(
        id=str(customer.id),
        role="customer",
        name=f"{customer.given_name} {customer.family_name}",
    )


def customer_for_account(session: Session, account: Account) -> Customer:
    return session.get(Customer, account.customer_id)


def to_bill(request: Request, session: Session, invoice: Invoice) -> CustomerBill:
    account = session.get(Account, invoice.account_id)
    customer = customer_for_account(session, account)
    return CustomerBill(
        id=str(invoice.id),
        href=resource_href(request, f"customerBillManagement/v4/customerBill/{invoice.id}"),
        type_name="CustomerBill",
        billNo=invoice.bill_number,
        billDate=invoice.issue_date.isoformat(),
        billingPeriod=TimePeriod(
            startDateTime=invoice.period_start.isoformat(),
            endDateTime=invoice.period_end.isoformat(),
        ),
        state=_BILL_STATE[invoice.status],
        taxExcludedAmount=money(invoice.subtotal),
        taxIncludedAmount=money(invoice.total),
        amountDue=money(invoice.amount_due),
        remainingAmount=money(invoice.amount_due),
        billingAccount=ref(
            request,
            f"accountManagement/v4/billingAccount/{account.id}",
            account.account_number,
        ),
        relatedParty=[_party(customer)],
    )


def to_rate(request: Request, session: Session, line: InvoiceLine, invoice: Invoice) -> AppliedRate:
    account = session.get(Account, invoice.account_id)
    product = None
    if line.subscription_id is not None:
        product = ref(request, f"productInventory/v4/product/{line.subscription_id}")
    return AppliedRate(
        id=str(line.id),
        href=resource_href(request, f"customerBillManagement/v4/appliedCustomerBillingRate/{line.id}"),
        type_name="AppliedCustomerBillingRate",
        date=invoice.issue_date.isoformat(),
        name=line.description,
        description=line.description,
        appliedBillingRateType=_RATE_TYPE[line.charge_type],
        taxExcludedAmount=money(line.amount),
        bill=ref(request, f"customerBillManagement/v4/customerBill/{invoice.id}", invoice.bill_number),
        billingAccount=ref(request, f"accountManagement/v4/billingAccount/{account.id}", account.account_number),
        product=product,
        characteristic=[
            Characteristic(name="chargeType", value=line.charge_type),
            Characteristic(name="quantity", value=f"{line.quantity:.3f}"),
            Characteristic(name="unitPrice", value=f"{line.unit_price:.4f}", unit="INR"),
            Characteristic(name="signedAmount", value=f"{line.amount:.2f}", unit="INR"),
        ],
    )


def to_usage(request: Request, session: Session, event: UsageEvent) -> Usage:
    subscription = session.get(Subscription, event.subscription_id)
    account = session.get(Account, subscription.account_id)
    customer = customer_for_account(session, account)
    usage_type = "roaming" if event.event_type.startswith("roaming") else event.event_type
    characteristics = [
        Characteristic(name="eventType", value=event.event_type),
        Characteristic(name="quantity", value=f"{event.quantity:.3f}"),
        Characteristic(name="unit", value=event.unit),
        Characteristic(name="sourceEventId", value=event.source_event_id),
        Characteristic(name="billed", value="true" if event.billed else "false"),
        Characteristic(name="ratingStatus", value=event.rating_status),
        Characteristic(name="ratedAmount", value=f"{event.rated_amount:.2f}", unit="INR"),
        Characteristic(name="rateApplied", value=f"{event.rate_applied:.4f}", unit="INR"),
    ]
    if event.roaming_country:
        characteristics.append(Characteristic(name="roamingCountry", value=event.roaming_country))
    if event.destination:
        characteristics.append(Characteristic(name="destination", value=event.destination))
    return Usage(
        id=str(event.id),
        href=resource_href(request, f"usageManagement/v4/usage/{event.id}"),
        type_name="Usage",
        usageDate=event.started_at.isoformat(),
        description=f"{event.event_type} {event.quantity:.3f} {event.unit}",
        status="received" if event.rating_status == "unbilled" else "rated",
        usageType=usage_type,
        usageCharacteristic=characteristics,
        ratedProductUsage=[
            {
                "@type": "RatedProductUsage",
                "isBilled": event.billed,
                "ratingDate": event.started_at.isoformat(),
                "taxExcludedRatingAmount": {"unit": "INR", "value": f"{event.rated_amount:.2f}"},
            }
        ],
        product=ref(request, f"productInventory/v4/product/{subscription.id}", subscription.msisdn),
        relatedParty=[_party(customer)],
    )


def to_offering(request: Request, plan: TariffPlan) -> ProductOffering:
    return ProductOffering(
        id=str(plan.id),
        href=resource_href(request, f"productCatalogManagement/v4/productOffering/{plan.id}"),
        type_name="ProductOffering",
        name=plan.name,
        description=plan.description,
        lifecycleStatus=plan.lifecycle_status,
        productOfferingPrice=[
            ProductOfferingPrice(
                name="Monthly fee",
                priceType="recurring",
                recurringChargePeriod="month",
                price=money(plan.monthly_fee),
            ),
            ProductOfferingPrice(
                name="Voice overage",
                priceType="usage",
                unitOfMeasure="minute",
                price=money(plan.voice_overage_rate),
            ),
            ProductOfferingPrice(
                name="Data overage",
                priceType="usage",
                unitOfMeasure="MB",
                price=money(plan.data_overage_rate),
            ),
            ProductOfferingPrice(
                name="SMS overage",
                priceType="usage",
                unitOfMeasure="message",
                price=money(plan.sms_overage_rate),
            ),
        ],
        prodSpecCharValueUse=[
            Characteristic(name="includedVoice", value=str(plan.included_voice_minutes), unit="minute"),
            Characteristic(name="includedData", value=str(plan.included_data_mb), unit="MB"),
            Characteristic(name="includedSms", value=str(plan.included_sms), unit="message"),
            Characteristic(name="voiceOverageRate", value=f"{plan.voice_overage_rate:.4f}", unit="INR"),
            Characteristic(name="dataOverageRate", value=f"{plan.data_overage_rate:.4f}", unit="INR"),
            Characteristic(name="smsOverageRate", value=f"{plan.sms_overage_rate:.4f}", unit="INR"),
            Characteristic(name="roamingDataRate", value=f"{plan.roaming_data_rate:.4f}", unit="INR"),
        ],
    )


def to_payment(request: Request, row: PaymentRow) -> Payment:
    item = []
    if row.invoice_id is not None:
        item.append(
            {
                "totalAmount": {"unit": "INR", "value": f"{row.amount:.2f}"},
                "item": {
                    "id": str(row.invoice_id),
                    "href": resource_href(request, f"customerBillManagement/v4/customerBill/{row.invoice_id}"),
                    "@referredType": "CustomerBill",
                },
            }
        )
    return Payment(
        id=str(row.id),
        href=resource_href(request, f"paymentManagement/v4/payment/{row.id}"),
        type_name="Payment",
        paymentDate=row.received_at.isoformat(),
        status=_PAYMENT_STATE[row.status],
        amount=money(row.amount),
        paymentMethod={"@type": "PaymentMethod", "name": row.method},
        account=ref(request, f"accountManagement/v4/billingAccount/{row.account_id}"),
        paymentItem=item,
        correlatorId=row.reference,
        characteristic=[
            Characteristic(name="internalStatus", value=row.status),
            Characteristic(
                name="postedAt",
                value="" if row.posted_at is None else row.posted_at.isoformat(),
            ),
        ],
    )


def to_attempt(request: Request, row: PaymentAttemptRow) -> PaymentAttempt:
    payment = None
    bill = None
    if row.payment_id is not None:
        payment = ref(request, f"paymentManagement/v4/payment/{row.payment_id}")
    if row.invoice_id is not None:
        bill = ref(request, f"customerBillManagement/v4/customerBill/{row.invoice_id}")
    return PaymentAttempt(
        id=str(row.id),
        href=resource_href(request, f"paymentManagement/v4/paymentAttempt/{row.id}"),
        type_name="PaymentAttempt",
        attemptDate=row.attempted_at.isoformat(),
        status=row.status,
        amount=money(row.amount),
        attemptNumber=row.attempt_number,
        paymentMethod={"@type": "PaymentMethod", "name": row.method},
        account=ref(request, f"accountManagement/v4/billingAccount/{row.account_id}"),
        payment=payment,
        customerBill=bill,
        failureReason=row.failure_reason,
    )


def to_subscription_product(request: Request, session: Session, row: Subscription) -> Product:
    account = session.get(Account, row.account_id)
    customer = customer_for_account(session, account)
    plan = session.get(TariffPlan, row.tariff_plan_id)
    return Product(
        id=str(row.id),
        href=resource_href(request, f"productInventory/v4/product/{row.id}"),
        type_name="Product",
        name=plan.name,
        status=_PRODUCT_STATUS[row.status],
        productType="subscription",
        startDate=row.started_at.isoformat(),
        terminationDate=None if row.ended_at is None else row.ended_at.isoformat(),
        billingAccount=ref(request, f"accountManagement/v4/billingAccount/{account.id}", account.account_number),
        productOffering=ref(request, f"productCatalogManagement/v4/productOffering/{plan.id}", plan.name),
        relatedParty=[_party(customer)],
        productCharacteristic=[
            Characteristic(name="msisdn", value=row.msisdn),
            Characteristic(name="imsi", value=row.imsi),
            Characteristic(name="simSerial", value=row.sim_serial),
            Characteristic(name="discountPercent", value=f"{row.discount_percent:.2f}"),
        ],
    )


def to_vas_product(request: Request, session: Session, row: VasSubscription) -> Product:
    subscription = session.get(Subscription, row.subscription_id)
    account = session.get(Account, subscription.account_id)
    customer = customer_for_account(session, account)
    return Product(
        id=str(row.id),
        href=resource_href(request, f"productInventory/v4/product/{row.id}"),
        type_name="Product",
        name=row.name,
        status=_PRODUCT_STATUS[row.status],
        productType="vas",
        startDate=row.started_at.isoformat(),
        terminationDate=None if row.ended_at is None else row.ended_at.isoformat(),
        billingAccount=ref(request, f"accountManagement/v4/billingAccount/{account.id}", account.account_number),
        relatedParty=[_party(customer)],
        productCharacteristic=[
            Characteristic(name="productCode", value=row.product_code),
            Characteristic(name="optedIn", value="true" if row.opted_in else "false"),
            Characteristic(name="monthlyFee", value=f"{row.monthly_fee:.2f}", unit="INR"),
            Characteristic(name="parentProductId", value=str(subscription.id)),
        ],
    )


def to_entitlement_product(request: Request, session: Session, row: Entitlement) -> Product:
    subscription = session.get(Subscription, row.subscription_id)
    account = session.get(Account, subscription.account_id)
    customer = customer_for_account(session, account)
    return Product(
        id=str(row.id),
        href=resource_href(request, f"productInventory/v4/product/{row.id}"),
        type_name="Product",
        name=row.feature_code,
        status=_PRODUCT_STATUS.get(row.status, row.status),
        productType="entitlement",
        startDate=row.valid_from.isoformat(),
        terminationDate=None if row.valid_to is None else row.valid_to.isoformat(),
        billingAccount=ref(request, f"accountManagement/v4/billingAccount/{account.id}", account.account_number),
        relatedParty=[_party(customer)],
        productCharacteristic=[
            Characteristic(name="featureCode", value=row.feature_code),
            Characteristic(name="sourceType", value=row.source_type),
            Characteristic(name="sourceRef", value=row.source_ref),
            Characteristic(name="allowance", value=f"{row.allowance_quantity:.3f}", unit=row.unit),
            Characteristic(name="resetsOnBillCycle", value="true" if row.resets_on_bill_cycle else "false"),
            Characteristic(name="parentProductId", value=str(subscription.id)),
        ],
    )


def to_ticket(request: Request, session: Session, row: Ticket) -> TroubleTicket:
    account = session.get(Account, row.account_id)
    customer = customer_for_account(session, account)
    return TroubleTicket(
        id=str(row.id),
        href=resource_href(request, f"troubleTicket/v4/troubleTicket/{row.id}"),
        type_name="TroubleTicket",
        name=row.summary,
        description=row.description,
        severity=row.severity,
        ticketType=row.ticket_type,
        status=_TICKET_STATUS[row.status],
        creationDate=row.opened_at.isoformat(),
        relatedParty=[_party(customer)],
        relatedEntity=[ref(request, f"accountManagement/v4/billingAccount/{account.id}", account.account_number)],
    )


def to_bucket(request: Request, balance: EntitlementBalance, entitlement: Entitlement) -> Bucket:
    return Bucket(
        id=str(balance.id),
        href=resource_href(request, f"prepayBalanceManagement/v4/bucket/{balance.id}"),
        type_name="Bucket",
        name=entitlement.feature_code,
        usageType=entitlement.feature_code,
        status=entitlement.status,
        remainingValue=Quantity(amount=balance.remaining_quantity, units=entitlement.unit),
        validFor=TimePeriod(
            startDateTime=balance.period_start.isoformat(),
            endDateTime=balance.period_end.isoformat(),
        ),
        product=ref(request, f"productInventory/v4/product/{entitlement.subscription_id}"),
        bucketCounter=[
            BucketCounter(
                counterType="granted",
                value=Quantity(amount=balance.granted_quantity, units=entitlement.unit),
            ),
            BucketCounter(
                counterType="consumed",
                value=Quantity(amount=balance.consumed_quantity, units=entitlement.unit),
            ),
        ],
    )


def to_dispute(request: Request, row: Dispute) -> CustomerBillDispute:
    bill = None
    ticket = None
    if row.invoice_id is not None:
        bill = ref(request, f"customerBillManagement/v4/customerBill/{row.invoice_id}")
    if row.ticket_id is not None:
        ticket = ref(request, f"troubleTicket/v4/troubleTicket/{row.ticket_id}")
    return CustomerBillDispute(
        id=str(row.id),
        href=resource_href(request, f"customerBillManagement/v4/customerBillDispute/{row.id}"),
        type_name="CustomerBillDispute",
        description=row.description,
        category=row.category,
        status=row.status,
        creationDate=row.opened_at.isoformat(),
        billingAccount=ref(request, f"accountManagement/v4/billingAccount/{row.account_id}"),
        customerBill=bill,
        troubleTicket=ticket,
    )


def to_adjustment(request: Request, row: Adjustment) -> BillAdjustment:
    bill = None
    if row.invoice_id is not None:
        bill = ref(request, f"customerBillManagement/v4/customerBill/{row.invoice_id}")
    return BillAdjustment(
        id=str(row.id),
        href=resource_href(request, f"customerBillManagement/v4/billAdjustment/{row.id}"),
        type_name="BillAdjustment",
        adjustmentType=row.adjustment_type,
        status=row.status,
        reason=row.reason,
        amount=money(row.amount),
        creationDate=row.proposed_at.isoformat(),
        billingAccount=ref(request, f"accountManagement/v4/billingAccount/{row.account_id}"),
        customerBill=bill,
        proposedBy=row.proposed_by,
        decidedBy=row.decided_by,
    )


def to_billing_account(
    request: Request,
    account: Account,
    customer: Customer,
    treatment: AccountTreatment | None,
    exemption: TreatmentExemption | None,
) -> BillingAccount:
    treatment_view = None
    if treatment is not None:
        treatment_view = TreatmentState(
            stage=treatment.stage,
            status=treatment.status,
            holdReason=treatment.hold_reason,
            startedAt=treatment.started_at.isoformat(),
        )
    exemption_view = None
    if exemption is not None:
        exemption_view = ExemptionState(
            reason=exemption.reason,
            validFor=TimePeriod(
                startDateTime=exemption.valid_from.isoformat(),
                endDateTime=exemption.valid_to.isoformat(),
            ),
        )
    return BillingAccount(
        id=str(account.id),
        href=resource_href(request, f"accountManagement/v4/billingAccount/{account.id}"),
        type_name="BillingAccount",
        name=account.account_number,
        state=account.status,
        treatment=treatment_view,
        exemption=exemption_view,
        relatedParty=[_party(customer)],
    )


def to_fraud_flag(request: Request, row: FraudFlag) -> FraudFlagView:
    return FraudFlagView(
        id=str(row.id),
        href=resource_href(request, f"accountManagement/v4/fraudFlag/{row.id}"),
        type_name="FraudFlag",
        flagType=row.flag_type,
        severity=row.severity,
        status=row.status,
        detectedAt=row.detected_at.isoformat(),
        billingAccount=ref(request, f"accountManagement/v4/billingAccount/{row.account_id}"),
        evidence=row.evidence,
    )


def to_audit(row: AuditLog) -> AuditEntry:
    return AuditEntry(
        id=str(row.id),
        occurredAt=row.occurred_at.isoformat(),
        actorRole=row.actor_role,
        actorId=row.actor_id,
        action=row.action,
        resourceType=row.resource_type,
        resourceId=str(row.resource_id),
        requestId=row.request_id,
        accountId=None if row.account_id is None else str(row.account_id),
        payload=row.payload,
    )
