"""
Abstract payment customer model — maps application users to payment provider customers.

Subclass and add your user FK:

    class PaymentCustomer(AbstractPaymentCustomer):
        user = models.ForeignKey('auth.User', on_delete=models.CASCADE)
        connection = models.ForeignKey('myapp.PaymentConnection', on_delete=models.CASCADE)
"""

from __future__ import annotations

from django.db import models


class AbstractPaymentCustomer(models.Model):
    """
    Maps an application user to a payment provider customer ID.

    Each record represents a user's identity at a specific payment provider
    (e.g. Stripe ``cus_xxx``). The ``connection`` FK determines which provider
    account is used.

    Subclass this and add:
    - A FK to your User model
    - A FK to your concrete Connection model
    """

    # connection FK — add in concrete model pointing to your Connection subclass
    provider_customer_id = models.CharField(
        max_length=255,
        help_text="Payment provider's customer ID (e.g. Stripe cus_xxx).",
    )
    email = models.EmailField(blank=True, default="")
    name = models.CharField(max_length=255, blank=True, default="")
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True

    def __str__(self):
        return f"{self.email or self.name} ({self.provider_customer_id})"
