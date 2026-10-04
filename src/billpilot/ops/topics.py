"""Topic names from the architecture deck, plus provisioning.

Provisioning is not a deck topic. Entitlement and provisioning mismatches are
different failures, so they do not share a topic.
"""

TOPICS: tuple[str, ...] = (
    "usage.rated",
    "bill.run",
    "payment.events",
    "treatment.actions",
    "entitlement.changes",
    "provisioning.events",
    "system.errors",
)

CONSUMER_NAME = "failures"
