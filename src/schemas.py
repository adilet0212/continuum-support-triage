from enum import Enum
from pydantic import BaseModel, Field

class TicketCategory(str, Enum):
    billing = "billing"
    technical = "technical"
    account = "account"
    general = "general"
    feedback = "feedback"

class ClassificationOutput(BaseModel):
    category: TicketCategory = Field(
        description=(
            "Category of the ticket, judged on what the customer is asking for — "
            "not on which system happens to be mentioned. "
            "billing: money moving the wrong way or questions about it — charges, "
            "duplicate charges, refunds, invoices, payment methods, subscription plans. "
            "technical: something the product does is broken — bugs, errors, outages, "
            "API failures, degraded performance, unexpected behaviour. "
            "account: the customer cannot get into or manage their own account — login "
            "failures, password and authentication problems, sign-up, permissions, "
            "profile and account settings. "
            "general: a genuine question or request that fits none of the above — how a "
            "feature works, where to find a setting, how to export data, pricing or "
            "policy information, status of an existing request. "
            "feedback: praise, criticism, or an opinion with no request attached; the "
            "customer wants nothing done. "
            "When a ticket mentions a technical symptom but the customer's actual problem "
            "is access to their own account, classify it as account."
        )
    )
    confidence: float = Field(
        ge=0, le=1,
        description=(
            "Confidence in this category, 0 to 1. Use 1.0 only when the ticket "
            "clearly and unambiguously fits one category. Lower it toward 0.5 when "
            "the ticket could plausibly fit two categories or lacks enough detail."
        )
    )
    reason: str = Field(
        max_length=400,
        description="One sentence: which words or phrases in the ticket drove this category."
    )

class TicketPriority(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"

class PriorityOutput(BaseModel):
    priority: TicketPriority = Field(
        description=(
            "Urgency of the ticket, judged on business impact and time sensitivity — "
            "not on how emotional the customer sounds. "
            "critical: production is down, a system is unusable, or many users are "
            "blocked right now; explicit urgency plus active breakage. "
            "high: the customer is materially harmed or out of pocket and needs action "
            "soon, but nothing is actively broken — e.g. a duplicate charge needing a refund. "
            "medium: a real problem that impairs one customer but has a self-service or "
            "documented workaround, or can wait a normal support cycle — e.g. a single "
            "user locked out of their account when password reset is available. "
            "low: no time pressure — routine questions, informational requests, and "
            "comments requiring no action."
        )
    )
    reason: str = Field(
        max_length=400,
        description="One sentence: what in the ticket drove this urgency level."
    )

class ResolutionOutput(BaseModel):
    resolved: bool = Field(
        description=(
            "True if the reply below fully answers the customer's request. False if the "
            "ticket needs information, access, or authority this agent does not have — "
            "in which case it will be escalated to a human."
        )
    )
    response_message: str = Field(
        max_length=1000,
        description=(
            "The reply sent to the customer: direct, specific, and complete. If resolved "
            "is false, instead state briefly what is missing and why a human is needed."
        )
    )