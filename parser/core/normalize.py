"""
Data normalization and cleaning functions.
"""
import re
from datetime import datetime, date
from decimal import Decimal
from typing import Any, Optional, Dict
import logging

logger = logging.getLogger(__name__)


def normalize_money(value: str, negative_if_cr: bool = False) -> Decimal:
    """
    Normalize money values by removing commas, spaces, and handling CR notation.
    
    Args:
        value: Raw money string
        negative_if_cr: If True, make negative when CR is present
    
    Returns:
        Decimal value
    """
    if not value or not value.strip():
        return Decimal('0.00')
    
    # Remove commas and spaces
    cleaned = re.sub(r'[,\s]', '', value.strip())
    
    # Handle CR notation
    is_credit = 'CR' in cleaned.upper()
    if is_credit:
        cleaned = re.sub(r'CR', '', cleaned, flags=re.IGNORECASE)
    
    # Handle parentheses (negative amounts)
    is_negative = cleaned.startswith('(') and cleaned.endswith(')')
    if is_negative:
        cleaned = cleaned[1:-1]
    
    # Extract numeric value
    match = re.search(r'-?\d+\.?\d*', cleaned)
    if not match:
        logger.warning(f"Could not extract numeric value from: {value}")
        return Decimal('0.00')
    
    amount = Decimal(match.group())
    
    # Apply negative logic
    if is_negative or (is_credit and negative_if_cr):
        amount = -abs(amount)
    
    return amount


def normalize_date(value: str, format_str: str, statement_year: int) -> Optional[date]:
    """
    Normalize date values with various formats.
    
    Args:
        value: Raw date string
        format_str: Expected format (e.g., "%d %b %Y", "%d %b")
        statement_year: Year to use if not specified in date
    
    Returns:
        Date object or None if parsing fails
    """
    if not value or not value.strip():
        return None
    
    cleaned = value.strip()
    
    try:
        # Try parsing with the specified format
        parsed_date = datetime.strptime(cleaned, format_str)
        
        # If year is not in the format, use statement year
        if '%Y' not in format_str:
            parsed_date = parsed_date.replace(year=statement_year)
        
        return parsed_date.date()
    
    except ValueError:
        # Try common alternative formats
        alternative_formats = [
            "%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d",
            "%d-%m-%Y", "%d.%m.%Y", "%d %B %Y"
        ]
        
        for alt_format in alternative_formats:
            try:
                parsed_date = datetime.strptime(cleaned, alt_format)
                if '%Y' not in alt_format:
                    parsed_date = parsed_date.replace(year=statement_year)
                return parsed_date.date()
            except ValueError:
                continue
        
        logger.warning(f"Could not parse date: {value}")
        return None


def normalize_text(value: str) -> str:
    """
    Normalize text by trimming and cleaning.
    
    Args:
        value: Raw text string
    
    Returns:
        Cleaned text string
    """
    if not value:
        return ""
    
    # Remove extra whitespace
    cleaned = re.sub(r'\s+', ' ', value.strip())
    
    return cleaned


def normalize_int(value: str) -> int:
    """
    Normalize integer values.
    
    Args:
        value: Raw integer string
    
    Returns:
        Integer value or 0 if parsing fails
    """
    if not value or not value.strip():
        return 0
    
    # Remove commas and spaces
    cleaned = re.sub(r'[,\s]', '', value.strip())
    
    try:
        return int(cleaned)
    except ValueError:
        logger.warning(f"Could not parse integer: {value}")
        return 0


def normalize_float(value: str) -> float:
    """
    Normalize float values.
    
    Args:
        value: Raw float string
    
    Returns:
        Float value or 0.0 if parsing fails
    """
    if not value or not value.strip():
        return 0.0
    
    # Remove commas and spaces
    cleaned = re.sub(r'[,\s]', '', value.strip())
    
    try:
        return float(cleaned)
    except ValueError:
        logger.warning(f"Could not parse float: {value}")
        return 0.0


def apply_post_processing(value: str, post_type: str, statement_year: int) -> Any:
    """
    Apply post-processing based on type.
    
    Args:
        value: Raw value string
        post_type: Processing type (e.g., "money", "date:%d %b %Y", "int")
        statement_year: Year for date parsing
    
    Returns:
        Processed value
    """
    if not value:
        return None
    
    if post_type == "trim":
        return normalize_text(value)
    
    elif post_type == "money":
        return normalize_money(value)
    
    elif post_type == "money_neg_if_cr":
        return normalize_money(value, negative_if_cr=True)
    
    elif post_type == "money:paren_or_cr":
        return normalize_money(value, negative_if_cr=True)
    
    elif post_type == "int":
        return normalize_int(value)
    
    elif post_type == "float":
        return normalize_float(value)
    
    elif post_type.startswith("date:"):
        format_str = post_type[5:]  # Remove "date:" prefix
        return normalize_date(value, format_str, statement_year)
    
    else:
        logger.warning(f"Unknown post-processing type: {post_type}")
        return normalize_text(value)


def extract_fx_info(description: str, fx_prefixes: list) -> Optional[Dict[str, Any]]:
    """
    Extract foreign exchange information from description.
    
    Args:
        description: Transaction description
        fx_prefixes: List of FX prefixes (e.g., ["USD ", "AUD ", "EUR "])
    
    Returns:
        FX info dict with currency and amount, or None
    """
    for prefix in fx_prefixes:
        if description.upper().startswith(prefix.upper()):
            # Extract amount after the currency prefix
            remaining = description[len(prefix):].strip()
            amount_match = re.search(r'(\d+\.?\d*)', remaining)
            
            if amount_match:
                return {
                    "currency": prefix.strip(),
                    "original_amount": float(amount_match.group(1))
                }
    
    return None


def determine_transaction_type(description: str, amount: Decimal) -> str:
    """
    Determine transaction type based on description and amount.
    
    Args:
        description: Transaction description
        amount: Transaction amount
    
    Returns:
        Transaction type ("purchase" or "payment")
    """
    desc_upper = description.upper()
    
    # Check for payment indicators
    payment_indicators = ["PAYMENT", "CREDIT", "REFUND", "REVERSAL"]
    
    for indicator in payment_indicators:
        if indicator in desc_upper:
            return "payment"
    
    # If amount is negative, likely a payment/credit
    if amount < 0:
        return "payment"
    
    return "purchase"


def clean_merchant_name(merchant: str) -> str:
    """
    Clean merchant name by removing common suffixes and normalizing.
    
    Args:
        merchant: Raw merchant name
    
    Returns:
        Cleaned merchant name
    """
    if not merchant:
        return ""
    
    # Remove common suffixes
    suffixes_to_remove = [
        " SINGAPORE SG",
        " SINGAPORE",
        " SG",
        " Transaction Ref",
        r"#\d+/\d+~~",
        r"\d+/\d+~~"
    ]
    
    cleaned = merchant
    for suffix in suffixes_to_remove:
        cleaned = re.sub(suffix, "", cleaned, flags=re.IGNORECASE)
    
    # Normalize whitespace
    cleaned = normalize_text(cleaned)
    
    return cleaned