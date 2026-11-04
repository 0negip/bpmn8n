"""ACME Corp: example tasks for three business processes. Each @task is an endpoint that the
matching n8n BPMN node lists automatically (see /api/docs)."""
import re
import uuid
from typing import Literal

from django.core.mail import send_mail
from ninja import Schema
from pydantic import Field

from bpmn8n.api import task
from bpmn8n.models import MessageSubscription


# --- field cookbook ---------------------------------------------------------------
# A task's input is a Schema; each field becomes an Input field of the n8n node and, with
# "Input From: Text", something GLiNER2.5 extracts. The node sends text: pydantic converts it.
# Uncomment and adapt (imports: from datetime import date, datetime / from decimal import Decimal).
#
# class Address(Schema):
#     city: str = Field(description="City")
#
# class Order(Schema):
#     customer: str = Field(description="Company placing the order")             # required text
#     note: str = Field("", description="Free notes")                            # optional, default ""
#     coupon: str | None = Field(None, description="Discount code, if any")      # optional, may be None
#     quantity: int = Field(1, ge=1, le=1000, description="Number of items")     # "3" -> 3, checked 1..1000
#     total: Decimal = Field(description="Order total, with currency")           # money: Decimal, not float
#     express: bool = Field(False, description="Did the customer ask for express shipping?")  # "true"/"false"; Laya judges it from text
#     priority: Literal["low", "normal", "high"] = Field("normal", description="How urgent")  # a dropdown in n8n
#     delivery: date = Field(description="Delivery date")                        # ISO text: "2026-11-20"
#     received_at: datetime | None = Field(None, description="When the order arrived")  # "2026-11-20T09:30"
#     items: list[str] = Field(default_factory=list, description="Product codes")  # from a variable: {{items}}
#     shipping: Address | None = Field(None, description="Where to ship")        # nested Schema: {{shipping}}
#     reference: str = Field(pattern=r"^PO-\d+$", description="Purchase order number, like PO-123")  # validated format
#
# @task("serviceTask")
# def place_order(request, data: Order):                                        # `-> OrderResult`: an output Schema
#     """Places the order in the ERP."""                                          # the node's description
#     return {"order_id": new_id("ORD"), "total": str(data.total)}              # becomes process variables
#
# Lists and nested objects come whole from a lone {{variable}}; in free text GLiNER finds only
# text, numbers, yes/no and choices, so give dates as ISO text and leave lists to variables.


def new_id(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


# --- shared -----------------------------------------------------------------

class Notification(Schema):
    to: str = Field(description="Email address of the recipient")
    subject: str = Field(description="Subject line of the message")
    body: str = Field("", description="Text of the message")


class NotificationSent(Schema):
    sent: bool = Field(description="Was the message handed to the mail backend?")
    to: str = Field(description="Email address of the recipient")
    subject: str = Field(description="Subject line of the message")


@task("sendTask")
def send_notification(request, data: Notification) -> NotificationSent:
    """Sends an email through Django's mail backend (console in dev)."""
    send_mail(data.subject, data.body, None, [data.to])
    return {"sent": True, "to": data.to, "subject": data.subject}


# --- UC1 customer service: ticket triage ----------------------------------------

class Ticket(Schema):
    customer: str = Field(description="Company that wrote the ticket")
    message: str = Field(description="What the customer asks or reports")
    channel: Literal["email", "chat", "phone"] = Field("email", description="How the customer contacted us")


class TicketRecord(Schema):
    ticket_id: str = Field(description="The helpdesk's id of the ticket")
    customer: str = Field(description="Company that wrote the ticket")
    message: str = Field(description="What the customer asks or reports")


@task("serviceTask")
def register_ticket(request, data: Ticket) -> TicketRecord:  # an output Schema: documented, and checks know it
    """Registers the ticket in the helpdesk and returns its id."""
    return TicketRecord(ticket_id=new_id("TCK"), customer=data.customer, message=data.message)


class RefundRequest(Schema):
    amount: float = Field(description="Money amount to refund, with currency")
    duplicate_charge: bool = Field(False, description="Was the customer charged twice for the same thing?")


class Refund(Schema):
    refund: float = Field(description="Money amount to refund")
    automatic: bool = Field(description="Is it small enough to refund without approval?")


@task("businessRuleTask")
def calculate_refund(request, data: RefundRequest) -> Refund:
    """Duplicate charges are refunded in full; other refunds up to 100 are automatic, above
    that a manager must approve."""
    automatic = data.duplicate_charge or data.amount <= 100
    return {"refund": data.amount, "automatic": automatic}


class BugReport(Schema):
    ticket_id: str = Field(description="Ticket number, like TCK-1234")
    summary: str = Field(description="Short description of the problem")


@task("sendTask")
def open_bug_report(request, data: BugReport):
    """Files a bug report for engineering, linked to the ticket."""
    return {"issue_id": new_id("BUG"), "ticket_id": data.ticket_id, "summary": data.summary[:120]}


# --- UC2 finance: expense approval --------------------------------------------------

POLICY_LIMITS = {"meal": 60.0, "travel": 500.0, "hotel": 180.0, "other": 100.0}  # per person


class Expense(Schema):
    employee: str = Field(description="Email or name of the employee who paid")
    category: Literal["meal", "travel", "hotel", "other"] = Field(description="Kind of expense")
    amount: float = Field(description="Total amount paid, with currency")
    attendees: int = Field(1, description="Number of people the expense was for")


class PolicyCheck(Schema):
    within_policy: bool = Field(description="Is the expense within the per-person limit?")
    limit: float = Field(description="The limit for this category and number of people")
    excess: float = Field(description="How much it is over the limit")


@task("businessRuleTask")
def check_expense_policy(request, data: Expense) -> PolicyCheck:
    """Per-person limit by category (meal 60, travel 500, hotel 180, other 100)."""
    limit = POLICY_LIMITS[data.category] * max(data.attendees, 1)
    return {"within_policy": data.amount <= limit, "limit": limit, "excess": round(max(0, data.amount - limit), 2)}


class ExpenseRecord(Schema):
    employee: str = Field(description="Email or name of the employee")
    amount: float = Field(description="Amount of the expense")
    approved: bool = Field(description="Was the expense approved?")


class ExpenseBooking(Schema):
    expense_id: str = Field(description="The accounting system's id of the booking")
    status: str = Field(description="queued for payment, or rejected")


@task("serviceTask")
def record_expense(request, data: ExpenseRecord) -> ExpenseBooking:
    """Books the expense in the accounting system (approved ones are queued for payment)."""
    return {"expense_id": new_id("EXP"), "status": "queued for payment" if data.approved else "rejected"}


# --- UC3 security: incident response -----------------------------------------------

class Alert(Schema):
    source: str = Field(description="System that raised the alert, like EDR or DLP")
    raw: str = Field(description="Text of the alert")


@task("scriptTask")
def normalize_alert(request, data: Alert):
    """Collapses whitespace and extracts hostnames (host-123) and IPv4 addresses."""
    text = re.sub(r"\s+", " ", data.raw).strip()
    return {
        "summary": text,
        "hosts": sorted(set(re.findall(r"\b[a-z]+-\d+\b", text))),
        "ips": sorted(set(re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", text))),
    }


class Host(Schema):
    hostname: str = Field("unknown", description="Name of the computer, like host-42")


@task("serviceTask")
def isolate_host(request, data: Host):
    """Asks the EDR to cut the host off the network."""
    return {"isolated": data.hostname, "ticket": new_id("EDR")}


class Account(Schema):
    username: str = Field(description="User account name")


@task("serviceTask")
def reset_credentials(request, data: Account):
    """Forces a password reset and revokes active sessions in the identity provider."""
    return {"reset": data.username, "sessions_revoked": True}


# --- UC4 library lending (course lesson 2) -----------------------------------------

# Demo catalogue: these books are on loan until the reader has put a hold on them (then they
# come back). The state lives in the database (the hold-book message bpmn8n received), never in
# process memory: with several worker processes each request may reach a different one.
ON_LOAN = {"Dune", "The Name of the Rose"}


class BookRequest(Schema):
    request_id: str = Field(description="Request number")
    book: str = Field(description="Title of the book")


def held(request_id):
    return MessageSubscription.objects.filter(name="hold-book", correlation_key=request_id,
                                              status=MessageSubscription.COMPLETED).exists()


@task("serviceTask")
def get_book_status(request, data: BookRequest):
    """Asks the catalogue whether the book is on the shelf."""
    available = data.book not in ON_LOAN or held(data.request_id)
    return {"request_id": data.request_id, "book": data.book, "available": available}


@task("serviceTask")
def hold_book(request, data: BookRequest):
    """Puts the reader in the reservation queue for the book."""
    return {"request_id": data.request_id, "held": True}


@task("serviceTask")
def update_catalogue(request, data: BookRequest):
    """Marks the book as lent in the catalogue."""
    return {"request_id": data.request_id, "book": data.book, "status": "on loan"}
