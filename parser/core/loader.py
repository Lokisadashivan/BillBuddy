"""
PDF loading and word extraction using pdfplumber.
"""
import pdfplumber
from pathlib import Path
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


class Word:
    """Represents a word with position information."""
    def __init__(self, text: str, x0: float, y0: float, x1: float, y1: float, 
                 top: float, bottom: float):
        self.text = text
        self.x0 = x0
        self.y0 = y0
        self.x1 = x1
        self.y1 = y1
        self.top = top
        self.bottom = bottom
    
    def __repr__(self):
        return f"Word('{self.text}', x0={self.x0:.1f}, y0={self.y0:.1f}, x1={self.x1:.1f}, y1={self.y1:.1f})"


class PageData:
    """Represents a page with extracted words and metadata."""
    def __init__(self, page_num: int, width: float, height: float, words: List[Word]):
        self.page_num = page_num
        self.width = width
        self.height = height
        self.words = words
    
    def get_words_in_region(self, x0: float, y0: float, x1: float, y1: float) -> List[Word]:
        """Get words within a rectangular region."""
        return [
            word for word in self.words
            if (x0 <= word.x0 <= x1 and y0 <= word.y0 <= y1) or
               (x0 <= word.x1 <= x1 and y0 <= word.y1 <= y1)
        ]
    
    def get_words_on_line(self, y: float, tolerance: float = 2.0) -> List[Word]:
        """Get words on the same horizontal line (within tolerance)."""
        return [
            word for word in self.words
            if abs(word.y0 - y) <= tolerance
        ]


class PDFLoader:
    """Handles PDF loading and word extraction."""
    
    def __init__(self, pdf_path: Path):
        self.pdf_path = pdf_path
        self._pdf = None
        self._pages = []
    
    def load(self) -> List[PageData]:
        """Load PDF and extract words from all pages."""
        if self._pages:
            return self._pages
        
        try:
            self._pdf = pdfplumber.open(self.pdf_path)
            logger.info(f"Loaded PDF with {len(self._pdf.pages)} pages")
            
            for i, page in enumerate(self._pdf.pages, 1):
                # Extract words with position information
                words_data = page.extract_words(
                    x_tolerance=1,
                    y_tolerance=2,
                    keep_blank_chars=False,
                    use_text_flow=True
                )
                
                # Convert to Word objects
                words = []
                for word_data in words_data:
                    # Normalize ligatures and clean text
                    text = self._normalize_text(word_data.get('text', ''))
                    if text.strip():  # Skip empty words
                        words.append(Word(
                            text=text,
                            x0=word_data.get('x0', 0),
                            y0=word_data.get('y0', 0),
                            x1=word_data.get('x1', 0),
                            y1=word_data.get('y1', 0),
                            top=word_data.get('top', 0),
                            bottom=word_data.get('bottom', 0)
                        ))
                
                page_data = PageData(
                    page_num=i,
                    width=page.width,
                    height=page.height,
                    words=words
                )
                self._pages.append(page_data)
                logger.debug(f"Page {i}: {len(words)} words extracted")
            
            return self._pages
            
        except Exception as e:
            logger.error(f"Error loading PDF: {e}")
            raise
    
    def _normalize_text(self, text: str) -> str:
        """Normalize text by handling ligatures and multiple spaces."""
        # Handle common ligatures
        ligatures = {
            'ﬁ': 'fi',
            'ﬂ': 'fl',
            'ﬀ': 'ff',
            'ﬃ': 'ffi',
            'ﬄ': 'ffl',
            'ﬆ': 'st',
            'ﬅ': 'st'
        }
        
        for ligature, replacement in ligatures.items():
            text = text.replace(ligature, replacement)
        
        # Collapse multiple spaces
        import re
        text = re.sub(r'\s+', ' ', text)
        
        return text.strip()
    
    def get_page(self, page_num: int) -> Optional[PageData]:
        """Get a specific page by number (1-indexed)."""
        if not self._pages:
            self.load()
        
        if 1 <= page_num <= len(self._pages):
            return self._pages[page_num - 1]
        return None
    
    def close(self):
        """Close the PDF file."""
        if self._pdf:
            self._pdf.close()
            self._pdf = None