"""Request and response shapes for the learning mock.

Money values are decimal strings so a paise is never lost to binary floating point.
`@type` is the TMF resource name. This is not the full TMF schema.
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from billpilot.billing import money


class Money(BaseModel):
    unit: Literal["INR"] = "INR"
    value: Decimal

    @field_serializer("value")
    def as_text(self, value: Decimal) -> str:
        return f"{Decimal(value):.2f}"


class MoneyIn(BaseModel):
    unit: Literal["INR"]
    value: Decimal

    @field_validator("value")
    @classmethod
    def positive_money(cls, value: Decimal) -> Decimal:
        if value <= 0:
            raise ValueError("amount must be positive")
        return money(value)


class Quantity(BaseModel):
    amount: Decimal
    units: str

    @field_serializer("amount")
    def as_text(self, value: Decimal) -> str:
        return f"{Decimal(value):.3f}"


class Ref(BaseModel):
    id: str
    href: str | None = None
    name: str | None = None


class RelatedParty(BaseModel):
    id: str
    role: str
    name: str | None = None


class Characteristic(BaseModel):
    name: str
    value: str
    unit: str | None = None


class TimePeriod(BaseModel):
    startDateTime: str
    endDateTime: str


class Resource(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    href: str
    type_name: str = Field(alias="@type")


class CustomerBill(Resource):
    billNo: str
    billDate: str
    billingPeriod: TimePeriod
    state: str
    category: str = "normal"
    taxExcludedAmount: Money
    taxIncludedAmount: Money
    amountDue: Money
    remainingAmount: Money
    billingAccount: Ref
    relatedParty: list[RelatedParty]


class AppliedRate(Resource):
    date: str
    name: str
    description: str
    appliedBillingRateType: str
    taxExcludedAmount: Money
    bill: Ref
    billingAccount: Ref
    product: Ref | None = None
    characteristic: list[Characteristic]


class Usage(Resource):
    usageDate: str
    description: str
    status: str
    usageType: str
    usageCharacteristic: list[Characteristic]
    ratedProductUsage: list[dict]
    product: Ref
    relatedParty: list[RelatedParty]


class ProductOfferingPrice(BaseModel):
    name: str
    priceType: str
    price: Money
    recurringChargePeriod: str | None = None
    unitOfMeasure: str | None = None


class ProductOffering(Resource):
    name: str
    description: str
    isBundle: bool = False
    isSellable: bool = True
    lifecycleStatus: str
    productOfferingPrice: list[ProductOfferingPrice]
    prodSpecCharValueUse: list[Characteristic]


class Payment(Resource):
    paymentDate: str
    status: str
    amount: Money
    paymentMethod: dict
    account: Ref
    paymentItem: list[dict]
    correlatorId: str
    characteristic: list[Characteristic]


class PaymentAttempt(Resource):
    attemptDate: str
    status: str
    amount: Money
    attemptNumber: int
    paymentMethod: dict
    account: Ref
    payment: Ref | None = None
    customerBill: Ref | None = None
    failureReason: str | None = None


class Product(Resource):
    name: str
    status: str
    productType: str
    startDate: str | None = None
    terminationDate: str | None = None
    billingAccount: Ref
    productOffering: Ref | None = None
    relatedParty: list[RelatedParty]
    productCharacteristic: list[Characteristic]


class TroubleTicket(Resource):
    name: str
    description: str
    severity: str
    ticketType: str
    status: str
    creationDate: str
    relatedParty: list[RelatedParty]
    relatedEntity: list[Ref]


class BucketCounter(BaseModel):
    counterType: str
    value: Quantity


class Bucket(Resource):
    name: str
    usageType: str
    status: str
    remainingValue: Quantity
    validFor: TimePeriod
    product: Ref
    bucketCounter: list[BucketCounter]


class CustomerBillDispute(Resource):
    description: str
    category: str
    status: str
    creationDate: str
    billingAccount: Ref
    customerBill: Ref | None = None
    troubleTicket: Ref | None = None


class BillAdjustment(Resource):
    adjustmentType: str
    status: str
    reason: str
    amount: Money
    creationDate: str
    billingAccount: Ref
    customerBill: Ref | None = None
    proposedBy: str
    decidedBy: str | None = None


class AuditEntry(BaseModel):
    id: str
    occurredAt: str
    actorRole: str
    actorId: str
    action: str
    resourceType: str
    resourceId: str
    requestId: str
    accountId: str | None = None
    payload: dict


class AccountRef(BaseModel):
    id: UUID
    name: str | None = None


class DisputeCreate(BaseModel):
    billingAccount: AccountRef
    customerBill: AccountRef | None = None
    category: Literal["billing", "usage", "payment", "treatment", "entitlement", "other"]
    description: str = Field(min_length=3, max_length=2000)


class TicketCreate(BaseModel):
    billingAccount: AccountRef
    name: str = Field(min_length=3, max_length=200)
    description: str = Field(min_length=3, max_length=4000)
    severity: Literal["Minor", "Major", "Critical"] = "Minor"
    ticketType: str = Field(default="complaint", max_length=32)


class AdjustmentCreate(BaseModel):
    billingAccount: AccountRef
    customerBill: AccountRef
    adjustmentType: Literal["credit", "debit"]
    amount: MoneyIn
    reason: str = Field(min_length=3, max_length=500)


class ApprovalDecision(BaseModel):
    decision: Literal["approve", "reject"]
    note: str | None = Field(default=None, max_length=500)


def iso(value: datetime) -> str:
    return value.isoformat()
