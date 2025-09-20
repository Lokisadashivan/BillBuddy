"""
Standard Chartered eStatement Parser

A deterministic PDF parser for Standard Chartered credit card eStatements using
anchor-and-coordinates (A&C) approach with pdfplumber and Camelot fallback.
"""

__version__ = "1.0.0"
__author__ = "BillBuddy Team"

from .core.runner import parse_statement
from .core.detectors import detect_template
from .models.schema import StatementData, MetaData, SummaryData, Transaction, Instalment, RewardsData, RewardsByCard

__all__ = [
    "parse_statement",
    "detect_template", 
    "StatementData",
    "MetaData",
    "SummaryData",
    "Transaction",
    "Instalment",
    "RewardsData",
    "RewardsByCard"
]