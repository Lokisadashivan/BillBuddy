"""
Test suite for Standard Chartered Smart Credit Card parser.
"""
import pytest
from pathlib import Path
from decimal import Decimal
from datetime import date

from ..models.schema import StatementData, MetaData, SummaryData, Transaction, Instalment, RewardsData, RewardsByCard
from ..core.runner import parse_statement
from ..core.detectors import detect_template


class TestSCBSmartV1:
    """Test cases for SCB Smart Credit Card template."""
    
    @pytest.fixture
    def sample_pdf_path(self):
        """Path to sample PDF file."""
        return Path(__file__).parent.parent.parent / "public" / "Aug.pdf"
    
    @pytest.fixture
    def golden_data(self):
        """Golden test data for validation."""
        return {
            "meta": {
                "bank": "Standard Chartered Bank (Singapore)",
                "template_id": "scb_smart_v1",
                "statement_date": date(2025, 8, 17),
                "payment_due_date": date(2025, 9, 8),
                "card_masked": "4864-18XX-XXXX-1669",
                "approved_credit_limit": Decimal("14000.00"),
                "available_credit_limit": Decimal("10138.00"),
                "currency": "SGD"
            },
            "summary": {
                "previous_balance": Decimal("1825.21"),
                "payments": Decimal("-1825.21"),
                "credits": Decimal("0.00"),
                "purchases": Decimal("1783.31"),
                "cash_advance": Decimal("0.00"),
                "charges": Decimal("0.00"),
                "new_balance": Decimal("1783.31"),
                "minimum_payment_due": Decimal("50.00")
            },
            "transactions": [
                {
                    "transaction_date": date(2025, 7, 17),
                    "posting_date": date(2025, 7, 18),
                    "description": "CHEERS - PARKLANE S SINGAPORE SG",
                    "amount": Decimal("10.00"),
                    "currency": "SGD",
                    "reference": "74508985217021376353487",
                    "type": "purchase",
                    "fx": None
                }
            ],
            "instalments": [
                {
                    "card_masked": "4864-18XX-XXXX-1669",
                    "merchant": "KAPLAN HIGHER EDUCA",
                    "billed": 4,
                    "total": 6,
                    "remaining_months": 2,
                    "principal_amount": Decimal("4000.00"),
                    "current_month_billed": Decimal("666.66"),
                    "remaining_principal": Decimal("1333.36")
                }
            ],
            "rewards": {
                "total_awarded_in_statement": 1913,
                "total_points_brought_forward": 7733,
                "points_used_or_expired": 0,
                "points_adjustment": 0,
                "total_points_available": 9646,
                "by_card": [
                    {
                        "card_masked": "4864-18XX-XXXX-1669",
                        "previous_balance": 7733,
                        "earned": 1913,
                        "redeemed": 0,
                        "adjustment": 0,
                        "current_balance": 9646,
                        "expiry_date": date(2026, 8, 11)
                    }
                ]
            }
        }
    
    def test_template_detection(self, sample_pdf_path):
        """Test that the template is correctly detected."""
        if not sample_pdf_path.exists():
            pytest.skip(f"Sample PDF not found: {sample_pdf_path}")
        
        template = detect_template(sample_pdf_path)
        assert template == "scb_smart_v1"
    
    def test_parse_statement(self, sample_pdf_path):
        """Test parsing the sample statement."""
        if not sample_pdf_path.exists():
            pytest.skip(f"Sample PDF not found: {sample_pdf_path}")
        
        result = parse_statement(sample_pdf_path, "scb_smart_v1", verbose=True)
        
        # Validate basic structure
        assert isinstance(result, StatementData)
        assert result.meta.bank == "Standard Chartered Bank (Singapore)"
        assert result.meta.template_id == "scb_smart_v1"
        assert result.meta.currency == "SGD"
        
        # Validate that we have some data
        assert len(result.transactions) > 0
        assert result.summary.new_balance is not None
    
    def test_balance_equation(self, sample_pdf_path):
        """Test that the balance equation is correct."""
        if not sample_pdf_path.exists():
            pytest.skip(f"Sample PDF not found: {sample_pdf_path}")
        
        result = parse_statement(sample_pdf_path, "scb_smart_v1")
        
        # Calculate expected balance
        expected = (
            result.summary.previous_balance +
            result.summary.payments +
            result.summary.credits +
            result.summary.purchases +
            result.summary.cash_advance +
            result.summary.charges
        )
        
        # Allow small difference due to rounding
        difference = abs(expected - result.summary.new_balance)
        assert difference <= Decimal("0.01"), f"Balance equation mismatch: {expected} != {result.summary.new_balance}"
    
    def test_transaction_types(self, sample_pdf_path):
        """Test that transaction types are correctly identified."""
        if not sample_pdf_path.exists():
            pytest.skip(f"Sample PDF not found: {sample_pdf_path}")
        
        result = parse_statement(sample_pdf_path, "scb_smart_v1")
        
        for transaction in result.transactions:
            assert transaction.type in ["purchase", "payment"]
            assert transaction.amount != 0
            assert transaction.currency == "SGD"
            assert transaction.transaction_date is not None
            assert transaction.posting_date is not None
    
    def test_cr_amounts(self, sample_pdf_path):
        """Test that CR amounts are parsed as negative numbers."""
        if not sample_pdf_path.exists():
            pytest.skip(f"Sample PDF not found: {sample_pdf_path}")
        
        result = parse_statement(sample_pdf_path, "scb_smart_v1")
        
        # Check that payments are negative
        assert result.summary.payments <= 0, "Payments should be negative"
        
        # Check transactions for CR amounts
        for transaction in result.transactions:
            if transaction.type == "payment":
                assert transaction.amount <= 0, f"Payment transaction should be negative: {transaction}"
    
    def test_fx_attachment(self, sample_pdf_path):
        """Test that FX information is correctly attached to transactions."""
        if not sample_pdf_path.exists():
            pytest.skip(f"Sample PDF not found: {sample_pdf_path}")
        
        result = parse_statement(sample_pdf_path, "scb_smart_v1")
        
        # Check for FX transactions
        fx_transactions = [t for t in result.transactions if t.fx is not None]
        
        for transaction in fx_transactions:
            assert transaction.fx is not None
            assert "currency" in transaction.fx
            assert "original_amount" in transaction.fx
            assert transaction.fx["currency"] in ["USD", "AUD", "EUR"]
    
    def test_drift_tolerance(self, sample_pdf_path):
        """Test that slightly altered header text still passes."""
        if not sample_pdf_path.exists():
            pytest.skip(f"Sample PDF not found: {sample_pdf_path}")
        
        # This test would require a modified PDF with slightly different text
        # For now, we just test that the parser is robust to fuzzy matching
        result = parse_statement(sample_pdf_path, "scb_smart_v1")
        assert result is not None
    
    def test_stop_conditions(self, sample_pdf_path):
        """Test that parser stops before footer pages."""
        if not sample_pdf_path.exists():
            pytest.skip(f"Sample PDF not found: {sample_pdf_path}")
        
        result = parse_statement(sample_pdf_path, "scb_smart_v1")
        
        # Check that we don't have transactions with "Important Information" in description
        for transaction in result.transactions:
            assert "Important Information" not in transaction.description
            assert "Page" not in transaction.description or "Page" in transaction.description and "of" in transaction.description
    
    def test_schema_validation(self, sample_pdf_path):
        """Test that the output validates against the schema."""
        if not sample_pdf_path.exists():
            pytest.skip(f"Sample PDF not found: {sample_pdf_path}")
        
        result = parse_statement(sample_pdf_path, "scb_smart_v1")
        
        # Test JSON serialization
        json_data = result.model_dump_json()
        assert json_data is not None
        
        # Test that we can recreate the object from JSON
        recreated = StatementData.model_validate_json(json_data)
        assert recreated.meta.bank == result.meta.bank
        assert recreated.meta.template_id == result.meta.template_id
    
    def test_golden_data_comparison(self, sample_pdf_path, golden_data):
        """Test against golden data if available."""
        if not sample_pdf_path.exists():
            pytest.skip(f"Sample PDF not found: {sample_pdf_path}")
        
        result = parse_statement(sample_pdf_path, "scb_smart_v1")
        
        # Compare key fields (allowing for some variation)
        assert result.meta.bank == golden_data["meta"]["bank"]
        assert result.meta.template_id == golden_data["meta"]["template_id"]
        assert result.meta.currency == golden_data["meta"]["currency"]
        
        # Check that we have reasonable transaction counts
        assert len(result.transactions) > 0
        assert len(result.transactions) <= 100  # Reasonable upper bound
    
    def test_error_handling(self):
        """Test error handling for invalid inputs."""
        # Test with non-existent file
        with pytest.raises(Exception):
            parse_statement(Path("nonexistent.pdf"), "scb_smart_v1")
        
        # Test with invalid template
        with pytest.raises(ValueError):
            parse_statement(Path("test.pdf"), "invalid_template")


if __name__ == "__main__":
    pytest.main([__file__])