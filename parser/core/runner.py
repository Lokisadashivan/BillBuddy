"""
End-to-end parsing orchestration.
"""
from pathlib import Path
from typing import Dict, Any, Optional
import logging
from decimal import Decimal

from .loader import PDFLoader
from .detectors import TemplateDetector
from .anchors import extract_field_value, RegionExtractor
from .tables import TableExtractor, extract_instalments, extract_rewards_table, CamelotFallback
from .normalize import apply_post_processing
from ..models.schema import StatementData, MetaData, SummaryData, Transaction, Instalment, RewardsData, RewardsByCard

logger = logging.getLogger(__name__)


class StatementParser:
    """Main parser class that orchestrates the entire parsing process."""
    
    def __init__(self, template_id: str, fallback_camelot: bool = False, verbose: bool = False):
        self.template_id = template_id
        self.fallback_camelot = fallback_camelot
        self.verbose = verbose
        
        # Load template
        detector = TemplateDetector()
        self.template = detector.get_template(template_id)
        if not self.template:
            raise ValueError(f"Template not found: {template_id}")
        
        if verbose:
            logging.basicConfig(level=logging.DEBUG)
    
    def parse(self, pdf_path: Path) -> StatementData:
        """
        Parse a PDF file into structured data.
        
        Args:
            pdf_path: Path to PDF file
        
        Returns:
            StatementData object
        """
        loader = PDFLoader(pdf_path)
        try:
            pages = loader.load()
            
            if not pages:
                raise ValueError("No pages found in PDF")
            
            # Extract metadata and summary
            meta = self._extract_metadata(pages)
            summary = self._extract_summary(pages, meta.statement_date.year)
            
            # Extract transactions
            transactions = self._extract_transactions(pages, meta.statement_date.year)
            
            # Extract instalments
            instalments = self._extract_instalments(pages, meta.statement_date.year)
            
            # Extract rewards
            rewards = self._extract_rewards(pages, meta.statement_date.year)
            
            return StatementData(
                meta=meta,
                summary=summary,
                transactions=transactions,
                instalments=instalments,
                rewards=rewards
            )
            
        finally:
            loader.close()
    
    def _extract_metadata(self, pages) -> MetaData:
        """Extract metadata from the first page."""
        page = pages[0]
        statement_year = None
        
        # Extract fields from template configuration
        fields_config = self.template.get('fields', {})
        extracted_fields = {}
        
        for field_name, field_config in fields_config.items():
            value = extract_field_value(page, field_config, 2025)  # Default year
            if value is not None:
                extracted_fields[field_name] = value
                
                # Extract year from statement_date for other fields
                if field_name == 'statement_date' and hasattr(value, 'year'):
                    statement_year = value.year
        
        # Re-extract fields with correct year
        if statement_year:
            for field_name, field_config in fields_config.items():
                if field_name not in extracted_fields:
                    value = extract_field_value(page, field_config, statement_year)
                    if value is not None:
                        extracted_fields[field_name] = value
        
        # Create MetaData object
        return MetaData(
            bank=self.template.get('bank', 'Standard Chartered Bank (Singapore)'),
            template_id=self.template_id,
            statement_date=extracted_fields.get('statement_date'),
            payment_due_date=extracted_fields.get('payment_due_date'),
            card_masked=extracted_fields.get('card_masked', ''),
            approved_credit_limit=extracted_fields.get('approved_credit_limit', Decimal('0')),
            available_credit_limit=extracted_fields.get('available_credit_limit', Decimal('0')),
            currency='SGD'
        )
    
    def _extract_summary(self, pages, statement_year: int) -> SummaryData:
        """Extract summary data from the first page."""
        page = pages[0]
        fields_config = self.template.get('fields', {})
        
        # Extract summary fields
        summary_fields = [
            'previous_balance', 'payments', 'credits', 'purchases',
            'cash_advance', 'charges', 'new_balance', 'minimum_payment_due'
        ]
        
        extracted_fields = {}
        for field_name in summary_fields:
            if field_name in fields_config:
                value = extract_field_value(page, fields_config[field_name], statement_year)
                if value is not None:
                    extracted_fields[field_name] = value
        
        return SummaryData(
            previous_balance=extracted_fields.get('previous_balance', Decimal('0')),
            payments=extracted_fields.get('payments', Decimal('0')),
            credits=extracted_fields.get('credits', Decimal('0')),
            purchases=extracted_fields.get('purchases', Decimal('0')),
            cash_advance=extracted_fields.get('cash_advance', Decimal('0')),
            charges=extracted_fields.get('charges', Decimal('0')),
            new_balance=extracted_fields.get('new_balance', Decimal('0')),
            minimum_payment_due=extracted_fields.get('minimum_payment_due', Decimal('0'))
        )
    
    def _extract_transactions(self, pages, statement_year: int) -> list[Transaction]:
        """Extract transactions from all relevant pages."""
        transactions_config = self.template.get('transactions', {})
        pages_config = transactions_config.get('pages', {})
        start_after_page = pages_config.get('start_after_page', 1)
        stop_anchors = pages_config.get('stop_on_anchors', [])
        
        all_transactions = []
        
        for page in pages[start_after_page:]:
            # Check if we should stop on this page
            should_stop = False
            for anchor in stop_anchors:
                match = RegionExtractor.find_anchor(page.words, anchor, 85)
                if match:
                    should_stop = True
                    break
            
            if should_stop:
                break
            
            # Extract transactions from this page
            page_transactions = self._extract_page_transactions(page, statement_year, transactions_config)
            all_transactions.extend(page_transactions)
        
        return all_transactions
    
    def _extract_page_transactions(self, page, statement_year: int, transactions_config: Dict[str, Any]) -> list[Transaction]:
        """Extract transactions from a single page."""
        columns = transactions_config.get('columns', [])
        header_config = transactions_config.get('header', {})
        row_gap = transactions_config.get('row_gap', 7)
        reference_prefix = transactions_config.get('reference_prefix')
        fx_prefixes = transactions_config.get('fx_inline_line_prefixes', [])
        
        # Create table extractor
        extractor = TableExtractor(page, columns)
        
        # Extract transaction data
        transaction_data = extractor.extract_transactions(
            header_config, statement_year, row_gap, reference_prefix, fx_prefixes
        )
        
        # Convert to Transaction objects
        transactions = []
        for data in transaction_data:
            try:
                transaction = Transaction(
                    transaction_date=data['transaction_date'],
                    posting_date=data['posting_date'],
                    description=data['description'],
                    amount=data['amount'],
                    currency=data.get('currency', 'SGD'),
                    reference=data.get('reference'),
                    type=data.get('type', 'purchase'),
                    fx=data.get('fx')
                )
                transactions.append(transaction)
            except Exception as e:
                logger.warning(f"Error creating transaction: {e}")
                continue
        
        # Try Camelot fallback if no transactions found and fallback is enabled
        if not transactions and self.fallback_camelot:
            logger.info("No transactions found, trying Camelot fallback")
            camelot_data = CamelotFallback.extract_table(
                str(page.page_num),  # This would need the PDF path
                page.page_num,
                (0, 0, page.width, page.height),  # Full page area
                [col['name'] for col in columns]
            )
            
            for data in camelot_data:
                try:
                    transaction = Transaction(
                        transaction_date=data.get('transaction_date'),
                        posting_date=data.get('posting_date', data.get('transaction_date')),
                        description=data.get('description', ''),
                        amount=Decimal(str(data.get('amount', '0'))),
                        currency='SGD',
                        reference=data.get('reference'),
                        type='purchase'
                    )
                    transactions.append(transaction)
                except Exception as e:
                    logger.warning(f"Error creating Camelot transaction: {e}")
                    continue
        
        return transactions
    
    def _extract_instalments(self, pages, statement_year: int) -> list[Instalment]:
        """Extract instalment data."""
        instalments_config = self.template.get('instalments', {})
        if not instalments_config:
            return []
        
        anchor = instalments_config.get('anchor')
        columns = instalments_config.get('columns', [])
        
        all_instalments = []
        
        for page in pages:
            instalments_data = extract_instalments(page, anchor, columns, statement_year)
            
            for data in instalments_data:
                try:
                    instalment = Instalment(
                        card_masked=data['card_masked'],
                        merchant=data['merchant'],
                        billed=data['billed'],
                        total=data['total'],
                        remaining_months=data['remaining_months'],
                        principal_amount=data['principal_amount'],
                        current_month_billed=data['current_month_billed'],
                        remaining_principal=data['remaining_principal']
                    )
                    all_instalments.append(instalment)
                except Exception as e:
                    logger.warning(f"Error creating instalment: {e}")
                    continue
        
        return all_instalments
    
    def _extract_rewards(self, pages, statement_year: int) -> RewardsData:
        """Extract rewards data."""
        rewards_config = self.template.get('rewards', {})
        if not rewards_config:
            return RewardsData(
                total_awarded_in_statement=0,
                total_points_brought_forward=0,
                points_used_or_expired=0,
                points_adjustment=0,
                total_points_available=0,
                by_card=[]
            )
        
        # Extract summary fields
        fields_config = rewards_config.get('fields', {})
        summary_fields = {}
        
        for page in pages:
            for field_name, field_config in fields_config.items():
                if field_name not in summary_fields:
                    value = extract_field_value(page, field_config, statement_year)
                    if value is not None:
                        summary_fields[field_name] = value
        
        # Extract by-card table
        by_card_table_config = rewards_config.get('by_card_table', {})
        columns = by_card_table_config.get('columns', [])
        anchor = rewards_config.get('anchor', '360° REWARDS POINTS SUMMARY')
        
        all_rewards_by_card = []
        for page in pages:
            rewards_data = extract_rewards_table(page, anchor, columns, statement_year)
            
            for data in rewards_data:
                try:
                    rewards_by_card = RewardsByCard(
                        card_masked=data['card_masked'],
                        previous_balance=data['previous_balance'],
                        earned=data['earned'],
                        redeemed=data['redeemed'],
                        adjustment=data['adjustment'],
                        current_balance=data['current_balance'],
                        expiry_date=data['expiry_date']
                    )
                    all_rewards_by_card.append(rewards_by_card)
                except Exception as e:
                    logger.warning(f"Error creating rewards by card: {e}")
                    continue
        
        return RewardsData(
            total_awarded_in_statement=summary_fields.get('total_awarded_in_statement', 0),
            total_points_brought_forward=summary_fields.get('total_points_brought_forward', 0),
            points_used_or_expired=summary_fields.get('points_used_or_expired', 0),
            points_adjustment=summary_fields.get('points_adjustment', 0),
            total_points_available=summary_fields.get('total_points_available', 0),
            by_card=all_rewards_by_card
        )


def parse_statement(pdf_path: Path, template_id: str, 
                   fallback_camelot: bool = False, verbose: bool = False) -> StatementData:
    """
    Parse a Standard Chartered eStatement PDF.
    
    Args:
        pdf_path: Path to PDF file
        template_id: Template ID to use
        fallback_camelot: Enable Camelot fallback
        verbose: Enable verbose logging
    
    Returns:
        StatementData object
    """
    parser = StatementParser(template_id, fallback_camelot, verbose)
    return parser.parse(pdf_path)