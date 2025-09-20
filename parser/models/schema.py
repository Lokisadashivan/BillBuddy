"""
Pydantic models for Standard Chartered eStatement data.
"""
from datetime import date
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, validator
from decimal import Decimal


class MetaData(BaseModel):
    """Statement metadata."""
    bank: str = "Standard Chartered Bank (Singapore)"
    template_id: str
    statement_date: date
    payment_due_date: date
    card_masked: str
    approved_credit_limit: Decimal
    available_credit_limit: Decimal
    currency: str = "SGD"


class SummaryData(BaseModel):
    """Account summary information."""
    previous_balance: Decimal
    payments: Decimal
    credits: Decimal
    purchases: Decimal
    cash_advance: Decimal
    charges: Decimal
    new_balance: Decimal
    minimum_payment_due: Decimal


class Transaction(BaseModel):
    """Individual transaction record."""
    transaction_date: date
    posting_date: date
    description: str
    amount: Decimal
    currency: str = "SGD"
    reference: Optional[str] = None
    type: str = "purchase"  # "purchase" or "payment"
    fx: Optional[Dict[str, Any]] = None


class Instalment(BaseModel):
    """Instalment plan information."""
    card_masked: str
    merchant: str
    billed: int
    total: int
    remaining_months: int
    principal_amount: Decimal
    current_month_billed: Decimal
    remaining_principal: Decimal


class RewardsByCard(BaseModel):
    """Rewards points by card."""
    card_masked: str
    previous_balance: int
    earned: int
    redeemed: int
    adjustment: int
    current_balance: int
    expiry_date: date


class RewardsData(BaseModel):
    """Rewards points summary."""
    total_awarded_in_statement: int
    total_points_brought_forward: int
    points_used_or_expired: int
    points_adjustment: int
    total_points_available: int
    by_card: List[RewardsByCard]


class StatementData(BaseModel):
    """Complete statement data structure."""
    meta: MetaData
    summary: SummaryData
    transactions: List[Transaction]
    instalments: List[Instalment]
    rewards: RewardsData

    @validator('summary')
    def validate_balance_equation(cls, v):
        """Validate that the balance equation is approximately correct."""
        calculated = (
            v.previous_balance + 
            v.payments + 
            v.credits + 
            v.purchases + 
            v.cash_advance + 
            v.charges
        )
        difference = abs(calculated - v.new_balance)
        if difference > Decimal('0.01'):
            raise ValueError(
                f"Balance equation mismatch: {calculated} != {v.new_balance} "
                f"(difference: {difference})"
            )
        return v

    @validator('transactions')
    def validate_transaction_amounts(cls, v):
        """Validate that all transaction amounts are valid."""
        for txn in v:
            if txn.amount == 0:
                raise ValueError(f"Transaction amount cannot be zero: {txn.description}")
        return v