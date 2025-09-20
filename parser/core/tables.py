"""
Table extraction using pdfplumber and Camelot fallback.
"""
import camelot
from typing import List, Dict, Any, Optional, Tuple
import logging
from decimal import Decimal

from .loader import Word, PageData
from .normalize import apply_post_processing, extract_fx_info, determine_transaction_type, clean_merchant_name

logger = logging.getLogger(__name__)


class TableRow:
    """Represents a table row with column data."""
    def __init__(self, data: Dict[str, Any]):
        self.data = data
    
    def get(self, column: str, default=None):
        return self.data.get(column, default)
    
    def __repr__(self):
        return f"TableRow({self.data})"


class TableExtractor:
    """Extracts tables from PDF pages using column-based approach."""
    
    def __init__(self, page: PageData, columns: List[Dict[str, Any]]):
        self.page = page
        self.columns = columns
        self.rows = []
    
    def extract_transactions(self, header_config: Dict[str, Any], 
                           statement_year: int, row_gap: int = 7,
                           reference_prefix: str = None,
                           fx_prefixes: List[str] = None) -> List[Dict[str, Any]]:
        """
        Extract transaction rows from the page.
        
        Args:
            header_config: Header configuration for validation
            statement_year: Year for date parsing
            row_gap: Gap between rows in points
            reference_prefix: Prefix for reference lines
            fx_prefixes: List of FX prefixes for foreign transactions
        
        Returns:
            List of transaction dictionaries
        """
        # Find table header
        header_match = self._find_table_header(header_config)
        if not header_match:
            logger.warning("Could not find table header")
            return []
        
        # Get words after header
        header_y = header_match['y']
        words_after_header = [
            word for word in self.page.words
            if word.y0 > header_y + 5  # Small gap after header
        ]
        
        # Cluster words into rows
        rows = self._cluster_words_into_rows(words_after_header, row_gap)
        
        # Extract transaction data from rows
        transactions = []
        current_reference = None
        
        for row_words in rows:
            # Check if this is a reference line
            if reference_prefix and self._is_reference_line(row_words, reference_prefix):
                current_reference = self._extract_reference(row_words, reference_prefix)
                continue
            
            # Extract transaction data
            transaction = self._extract_transaction_row(
                row_words, statement_year, current_reference, fx_prefixes
            )
            
            if transaction:
                transactions.append(transaction)
                current_reference = None  # Reset reference after use
        
        return transactions
    
    def _find_table_header(self, header_config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Find the table header using fuzzy matching."""
        from .anchors import RegionExtractor
        
        labels = header_config.get('label', [])
        threshold = header_config.get('fuzzy_threshold', 80)
        
        # Look for header labels in sequence
        header_words = []
        for label in labels:
            match = RegionExtractor.find_anchor(self.page.words, label, threshold)
            if match:
                header_words.append(match.word)
            else:
                logger.warning(f"Header label '{label}' not found")
                return None
        
        if not header_words:
            return None
        
        # Use the first header word's position
        return {
            'y': min(word.y0 for word in header_words),
            'words': header_words
        }
    
    def _cluster_words_into_rows(self, words: List[Word], row_gap: int) -> List[List[Word]]:
        """Cluster words into rows based on vertical position."""
        if not words:
            return []
        
        # Sort words by vertical position
        sorted_words = sorted(words, key=lambda w: w.y0)
        
        rows = []
        current_row = []
        last_y = None
        
        for word in sorted_words:
            if last_y is None or (word.y0 - last_y) <= row_gap:
                # Same row
                current_row.append(word)
            else:
                # New row
                if current_row:
                    rows.append(current_row)
                current_row = [word]
            
            last_y = word.y0
        
        # Add the last row
        if current_row:
            rows.append(current_row)
        
        return rows
    
    def _is_reference_line(self, row_words: List[Word], reference_prefix: str) -> bool:
        """Check if a row is a reference line."""
        if not row_words:
            return False
        
        # Join all words in the row
        row_text = ' '.join(word.text for word in row_words)
        return reference_prefix.upper() in row_text.upper()
    
    def _extract_reference(self, row_words: List[Word], reference_prefix: str) -> Optional[str]:
        """Extract reference number from a reference line."""
        if not row_words:
            return None
        
        # Find the word after the reference prefix
        row_text = ' '.join(word.text for word in row_words)
        prefix_index = row_text.upper().find(reference_prefix.upper())
        
        if prefix_index == -1:
            return None
        
        # Get text after the prefix
        after_prefix = row_text[prefix_index + len(reference_prefix):].strip()
        
        # Extract the reference number (first sequence of digits)
        import re
        match = re.search(r'\d+', after_prefix)
        return match.group() if match else None
    
    def _extract_transaction_row(self, row_words: List[Word], statement_year: int,
                               reference: Optional[str], fx_prefixes: List[str]) -> Optional[Dict[str, Any]]:
        """Extract transaction data from a row of words."""
        if not row_words:
            return None
        
        # Assign words to columns based on x-position
        column_data = {}
        
        for col_config in self.columns:
            col_name = col_config['name']
            x1 = col_config['x1']
            x2 = col_config['x2']
            
            # Find words in this column
            col_words = [
                word for word in row_words
                if word.x0 >= x1 and word.x1 <= x2
            ]
            
            # Sort by x position and join
            col_words.sort(key=lambda w: w.x0)
            col_text = ' '.join(word.text for word in col_words)
            
            # Apply post-processing
            col_type = col_config.get('type', 'text')
            if col_type == 'text':
                column_data[col_name] = col_text.strip()
            else:
                column_data[col_name] = apply_post_processing(col_text, col_type, statement_year)
        
        # Validate that we have essential data
        if not column_data.get('transaction_date') or not column_data.get('amount'):
            return None
        
        # Clean up the data
        transaction = {
            'transaction_date': column_data['transaction_date'],
            'posting_date': column_data.get('posting_date', column_data['transaction_date']),
            'description': clean_merchant_name(column_data.get('description', '')),
            'amount': column_data['amount'],
            'currency': 'SGD',
            'reference': reference,
            'type': determine_transaction_type(
                column_data.get('description', ''), 
                column_data['amount']
            )
        }
        
        # Check for FX information
        if fx_prefixes:
            fx_info = extract_fx_info(transaction['description'], fx_prefixes)
            if fx_info:
                transaction['fx'] = fx_info
        
        return transaction


class CamelotFallback:
    """Fallback table extraction using Camelot."""
    
    @staticmethod
    def extract_table(pdf_path: str, page_num: int, 
                     table_area: Tuple[float, float, float, float],
                     columns: List[str]) -> List[Dict[str, Any]]:
        """
        Extract table using Camelot as fallback.
        
        Args:
            pdf_path: Path to PDF file
            page_num: Page number (1-indexed)
            table_area: (x1, y1, x2, y2) table area coordinates
            columns: List of column names
        
        Returns:
            List of row dictionaries
        """
        try:
            # Extract table using Camelot
            tables = camelot.read_pdf(
                pdf_path,
                pages=str(page_num),
                flavor='stream',
                table_areas=[table_area],
                columns=columns
            )
            
            if not tables:
                logger.warning("Camelot found no tables")
                return []
            
            table = tables[0]
            rows = []
            
            # Convert to list of dictionaries
            for i, row in table.df.iterrows():
                if i == 0:  # Skip header
                    continue
                
                row_data = {}
                for j, col_name in enumerate(columns):
                    if j < len(row):
                        row_data[col_name] = str(row.iloc[j]).strip()
                
                # Only add rows with valid data
                if any(row_data.values()):
                    rows.append(row_data)
            
            logger.info(f"Camelot extracted {len(rows)} rows")
            return rows
            
        except Exception as e:
            logger.error(f"Camelot extraction failed: {e}")
            return []


def extract_instalments(page: PageData, anchor: str, columns: List[Dict[str, Any]],
                       statement_year: int) -> List[Dict[str, Any]]:
    """
    Extract instalment data from a page.
    
    Args:
        page: Page data
        anchor: Anchor text to find
        columns: Column configuration
        statement_year: Year for date parsing
    
    Returns:
        List of instalment dictionaries
    """
    from .anchors import RegionExtractor
    
    # Find the anchor
    anchor_match = RegionExtractor.find_anchor(page.words, anchor, 85)
    if not anchor_match:
        logger.warning(f"Instalment anchor '{anchor}' not found")
        return []
    
    # Get words after the anchor
    anchor_y = anchor_match.word.y0
    words_after_anchor = [
        word for word in page.words
        if word.y0 > anchor_y + 10  # Gap after anchor
    ]
    
    # Cluster into rows
    extractor = TableExtractor(page, columns)
    rows = extractor._cluster_words_into_rows(words_after_anchor, 7)
    
    instalments = []
    for row_words in rows:
        if not row_words:
            continue
        
        # Extract column data
        row_data = {}
        for col_config in columns:
            col_name = col_config['name']
            x1 = col_config['x1']
            x2 = col_config['x2']
            
            col_words = [
                word for word in row_words
                if word.x0 >= x1 and word.x1 <= x2
            ]
            
            col_words.sort(key=lambda w: w.x0)
            col_text = ' '.join(word.text for word in col_words)
            
            col_type = col_config.get('type', 'text')
            if col_type == 'text':
                row_data[col_name] = col_text.strip()
            else:
                row_data[col_name] = apply_post_processing(col_text, col_type, statement_year)
        
        # Validate and create instalment record
        if row_data.get('card_masked') and row_data.get('principal_amount'):
            instalment = {
                'card_masked': row_data['card_masked'],
                'merchant': row_data.get('description', ''),
                'billed': int(row_data.get('billed_total', '0').split('/')[0]) if '/' in str(row_data.get('billed_total', '0')) else 0,
                'total': int(row_data.get('billed_total', '0').split('/')[1]) if '/' in str(row_data.get('billed_total', '0')) else 0,
                'remaining_months': row_data.get('remaining_months', 0),
                'principal_amount': row_data['principal_amount'],
                'current_month_billed': row_data.get('current_month_instalment', Decimal('0')),
                'remaining_principal': row_data.get('remaining_principal', Decimal('0'))
            }
            instalments.append(instalment)
    
    return instalments


def extract_rewards_table(page: PageData, anchor: str, columns: List[Dict[str, Any]],
                         statement_year: int) -> List[Dict[str, Any]]:
    """
    Extract rewards table data from a page.
    
    Args:
        page: Page data
        anchor: Anchor text to find
        columns: Column configuration
        statement_year: Year for date parsing
    
    Returns:
        List of rewards by card dictionaries
    """
    from .anchors import RegionExtractor
    
    # Find the anchor
    anchor_match = RegionExtractor.find_anchor(page.words, anchor, 85)
    if not anchor_match:
        logger.warning(f"Rewards anchor '{anchor}' not found")
        return []
    
    # Get words after the anchor
    anchor_y = anchor_match.word.y0
    words_after_anchor = [
        word for word in page.words
        if word.y0 > anchor_y + 10  # Gap after anchor
    ]
    
    # Cluster into rows
    extractor = TableExtractor(page, columns)
    rows = extractor._cluster_words_into_rows(words_after_anchor, 7)
    
    rewards_by_card = []
    for row_words in rows:
        if not row_words:
            continue
        
        # Extract column data
        row_data = {}
        for col_config in columns:
            col_name = col_config['name']
            x1 = col_config['x1']
            x2 = col_config['x2']
            
            col_words = [
                word for word in row_words
                if word.x0 >= x1 and word.x1 <= x2
            ]
            
            col_words.sort(key=lambda w: w.x0)
            col_text = ' '.join(word.text for word in col_words)
            
            col_type = col_config.get('type', 'text')
            if col_type == 'text':
                row_data[col_name] = col_text.strip()
            else:
                row_data[col_name] = apply_post_processing(col_text, col_type, statement_year)
        
        # Validate and create rewards record
        if row_data.get('card_masked'):
            rewards = {
                'card_masked': row_data['card_masked'],
                'previous_balance': row_data.get('previous_balance', 0),
                'earned': row_data.get('earned', 0),
                'redeemed': row_data.get('redeemed', 0),
                'adjustment': row_data.get('adjustment', 0),
                'current_balance': row_data.get('current_balance', 0),
                'expiry_date': row_data.get('expiry_date')
            }
            rewards_by_card.append(rewards)
    
    return rewards_by_card