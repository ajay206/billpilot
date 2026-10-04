"""One call opens a customer. CSR and ops can call it. The customer role cannot.

POST /onboarding is the deck's path. The same handler is also mounted on the
TMF-style customer-management path used by the rest of this mock.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from billpilot.api.audit import write_audit
from billpilot.api.present import resource_href
from billpilot.api.security import Principal, require_roles
from billpilot.db import get_session
from billpilot.onboarding.provision import ProvisionError
from billpilot.onboarding.service import open_customer

router = APIRouter(tags=["Onboarding"])


class OnboardingRequest(BaseModel):
    givenName: str = Field(min_length=1, max_length=80)
    familyName: str = Field(min_length=1, max_length=80)
    email: str = Field(min_length=3, max_length=255)
    phone: str = Field(min_length=8, max_length=20)
    city: str = Field(min_length=1, max_length=80)
    state: str = Field(min_length=1, max_length=80)
    msisdn: str = Field(min_length=1, max_length=15)
    planCode: str = Field(min_length=1, max_length=32)
    billingCycleDay: int = 1
    optedInVas: list[str] = Field(default_factory=list)


class PreviewLine(BaseModel):
    description: str
    chargeType: str
    amount: str


class FirstBillPreview(BaseModel):
    currency: str
    periodStart: str
    periodEnd: str
    dueDate: str
    subtotal: str
    tax: str
    total: str
    amountDue: str
    lines: list[PreviewLine]
    posted: bool


class EntitlementView(BaseModel):
    feature: str
    allowance: str
    unit: str
    status: str


class OnboardingResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    href: str
    type_name: str = Field(alias="@type")
    customerNumber: str
    accountId: str
    accountNumber: str
    subscriptionId: str
    msisdn: str
    planCode: str
    planName: str
    treatmentStage: str
    treatmentStatus: str
    creditClass: str
    creditLimit: str
    entitlements: list[EntitlementView]
    vas: list[str]
    welcomeMessage: str
    firstBillPreview: FirstBillPreview


def _create(
    body: OnboardingRequest,
    request: Request,
    session: Session,
    principal: Principal,
) -> OnboardingResponse:
    try:
        result = open_customer(session, principal, body)
    except ProvisionError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    treatment = result.treatment
    credit = result.credit
    if treatment is None or credit is None or result.preview is None:
        raise HTTPException(status_code=500, detail="Onboarding did not finish.")
    write_audit(
        session,
        principal,
        request,
        "onboarding.create",
        "customer",
        result.customer.id,
        result.account.id,
        {
            "customerNumber": result.customer.customer_number,
            "planCode": body.planCode,
            "msisdn": result.subscription.msisdn,
            "creditClass": credit.credit_class,
            "previewTotal": result.preview["total"],
            "posted": False,
        },
    )
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="That email or MSISDN is already in the ledger.") from exc
    request.app.state.publisher.publish(
        "entitlement.changes",
        {
            "action": "provisioned",
            "accountId": str(result.account.id),
            "subscriptionId": str(result.subscription.id),
            "features": [row.feature_code for row in result.entitlements],
            "vas": [row.product_code for row in result.vas],
        },
    )
    request.app.state.publisher.publish(
        "treatment.actions",
        {
            "action": "opened",
            "accountId": str(result.account.id),
            "stage": treatment.stage,
            "plan": "STANDARD",
        },
    )
    return OnboardingResponse(
        id=str(result.customer.id),
        href=resource_href(request, f"customerManagement/v4/onboarding/{result.customer.id}"),
        type_name="CustomerOnboarding",
        customerNumber=result.customer.customer_number,
        accountId=str(result.account.id),
        accountNumber=result.account.account_number,
        subscriptionId=str(result.subscription.id),
        msisdn=result.subscription.msisdn,
        planCode=result.plan_code,
        planName=result.plan_name,
        treatmentStage=treatment.stage,
        treatmentStatus=treatment.status,
        creditClass=credit.credit_class,
        creditLimit=f"{credit.credit_limit:.2f}",
        entitlements=[
            EntitlementView(
                feature=row.feature_code,
                allowance=f"{row.allowance_quantity:.3f}",
                unit=row.unit,
                status=row.status,
            )
            for row in result.entitlements
        ],
        vas=[row.product_code for row in result.vas],
        welcomeMessage=result.welcome,
        firstBillPreview=FirstBillPreview.model_validate(result.preview),
    )


@router.post(
    "/tmf-api/customerManagement/v4/onboarding",
    response_model=OnboardingResponse,
    status_code=201,
    tags=["Onboarding"],
)
def onboard_tmf(
    body: OnboardingRequest,
    request: Request,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_roles("csr", "ops")),
) -> OnboardingResponse:
    """TMF-style customer onboarding. Creates the party, the line, and a first-bill preview."""
    return _create(body, request, session, principal)


@router.post("/onboarding", response_model=OnboardingResponse, status_code=201, tags=["Onboarding"])
def onboard_short(
    body: OnboardingRequest,
    request: Request,
    session: Session = Depends(get_session),
    principal: Principal = Depends(require_roles("csr", "ops")),
) -> OnboardingResponse:
    """Deck path for the same onboarding call."""
    return _create(body, request, session, principal)
