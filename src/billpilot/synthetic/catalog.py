"""The sellable plans, add-ons and the collections ladder.

Rates are round on purpose so a wrong-rate fault is obvious when you recompute a line.
"""

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class Tariff:
    code: str
    name: str
    description: str
    monthly_fee: Decimal
    included_voice_minutes: int
    included_data_mb: int
    included_sms: int
    voice_overage_rate: Decimal
    data_overage_rate: Decimal
    sms_overage_rate: Decimal
    roaming_voice_rate: Decimal
    roaming_data_rate: Decimal
    roaming_sms_rate: Decimal

    def overage_rate(self, event_type: str) -> Decimal:
        return {
            "voice": self.voice_overage_rate,
            "data": self.data_overage_rate,
            "sms": self.sms_overage_rate,
            "roaming_voice": self.roaming_voice_rate,
            "roaming_data": self.roaming_data_rate,
            "roaming_sms": self.roaming_sms_rate,
        }[event_type]


TARIFFS: tuple[Tariff, ...] = (
    Tariff(
        code="SMART-199",
        name="Smart 199",
        description="Entry monthly plan with 200 minutes, 2 GB and 100 SMS.",
        monthly_fee=Decimal("199.00"),
        included_voice_minutes=200,
        included_data_mb=2048,
        included_sms=100,
        voice_overage_rate=Decimal("1.0000"),
        data_overage_rate=Decimal("0.0500"),
        sms_overage_rate=Decimal("0.2500"),
        roaming_voice_rate=Decimal("5.0000"),
        roaming_data_rate=Decimal("0.5000"),
        roaming_sms_rate=Decimal("1.0000"),
    ),
    Tariff(
        code="PLUS-399",
        name="Plus 399",
        description="Mid-tier monthly plan with 1,000 minutes, 10 GB and 300 SMS.",
        monthly_fee=Decimal("399.00"),
        included_voice_minutes=1000,
        included_data_mb=10240,
        included_sms=300,
        voice_overage_rate=Decimal("0.8000"),
        data_overage_rate=Decimal("0.0400"),
        sms_overage_rate=Decimal("0.2000"),
        roaming_voice_rate=Decimal("4.0000"),
        roaming_data_rate=Decimal("0.4000"),
        roaming_sms_rate=Decimal("1.0000"),
    ),
    Tariff(
        code="MAX-599",
        name="Max 599",
        description="Higher monthly plan with 3,000 minutes, 25 GB and 500 SMS.",
        monthly_fee=Decimal("599.00"),
        included_voice_minutes=3000,
        included_data_mb=25600,
        included_sms=500,
        voice_overage_rate=Decimal("0.5000"),
        data_overage_rate=Decimal("0.0300"),
        sms_overage_rate=Decimal("0.1500"),
        roaming_voice_rate=Decimal("3.0000"),
        roaming_data_rate=Decimal("0.3000"),
        roaming_sms_rate=Decimal("0.7500"),
    ),
    Tariff(
        code="ULTRA-999",
        name="Ultra 999",
        description="Large monthly plan with 5,000 minutes, 80 GB and 1,000 SMS.",
        monthly_fee=Decimal("999.00"),
        included_voice_minutes=5000,
        included_data_mb=81920,
        included_sms=1000,
        voice_overage_rate=Decimal("0.4000"),
        data_overage_rate=Decimal("0.0200"),
        sms_overage_rate=Decimal("0.1000"),
        roaming_voice_rate=Decimal("2.0000"),
        roaming_data_rate=Decimal("0.2000"),
        roaming_sms_rate=Decimal("0.5000"),
    ),
)

TARIFFS_BY_CODE = {tariff.code: tariff for tariff in TARIFFS}

CALLER_TUNE = {
    "code": "CALLER-TUNE",
    "name": "Caller tune",
    "monthly_fee": Decimal("30.00"),
}
OTT_MINI = {
    "code": "OTT-MINI",
    "name": "OTT Mini",
    "monthly_fee": Decimal("99.00"),
}

ROAM_ASIA = {
    "code": "ROAM-ASIA-1G",
    "name": "Asia roaming 1 GB",
    "zone": "Asia",
    "data_mb": 1024,
    "voice_minutes": 30,
    "price": Decimal("499.00"),
    "days": 7,
}
ROAM_WORLD = {
    "code": "ROAM-WORLD-3G",
    "name": "World roaming 3 GB",
    "zone": "World",
    "data_mb": 3072,
    "voice_minutes": 60,
    "price": Decimal("1499.00"),
    "days": 10,
}

# A promotional data bonus that the catalogue says lasts three months.
PROMO_CODE = "PROMO-3M"
PROMO_MONTHS = 3
PROMO_DATA_MB = 5120

STANDARD_TREATMENT = {
    "code": "STANDARD",
    "name": "Standard collections ladder",
    "description": ("Reminder, then soft bar, hard bar and disconnect. Days are counted from the invoice due date."),
    "reminder_after_days": 3,
    "soft_bar_after_days": 10,
    "hard_bar_after_days": 20,
    "disconnect_after_days": 45,
}

# Indian city and state pairs. Names come from Faker; geography stays coherent.
CITIES: tuple[tuple[str, str], ...] = (
    ("Mumbai", "Maharashtra"),
    ("Pune", "Maharashtra"),
    ("Nagpur", "Maharashtra"),
    ("Delhi", "Delhi"),
    ("Bengaluru", "Karnataka"),
    ("Hyderabad", "Telangana"),
    ("Chennai", "Tamil Nadu"),
    ("Kolkata", "West Bengal"),
    ("Jaipur", "Rajasthan"),
    ("Ahmedabad", "Gujarat"),
    ("Lucknow", "Uttar Pradesh"),
    ("Chandigarh", "Chandigarh"),
    ("Kochi", "Kerala"),
    ("Indore", "Madhya Pradesh"),
    ("Bhubaneswar", "Odisha"),
    ("Guwahati", "Assam"),
)

EVENT_UNITS = {
    "voice": "minute",
    "data": "MB",
    "sms": "message",
    "roaming_voice": "minute",
    "roaming_data": "MB",
    "roaming_sms": "message",
}

DOMESTIC_FEATURES = (
    ("voice", "minute", "included_voice_minutes"),
    ("data", "MB", "included_data_mb"),
    ("sms", "message", "included_sms"),
)
