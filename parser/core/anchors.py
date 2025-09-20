"""
Anchor finding and region extraction using fuzzy matching.
"""
from typing import List, Optional, Tuple, Dict, Any
from rapidfuzz import fuzz
import logging

from .loader import Word, PageData

logger = logging.getLogger(__name__)


class AnchorMatch:
    """Represents a found anchor with position and confidence."""
    def __init__(self, word: Word, confidence: float, target: str):
        self.word = word
        self.confidence = confidence
        self.target = target
    
    def __repr__(self):
        return f"AnchorMatch('{self.target}', confidence={self.confidence:.1f}, word={self.word})"


class RegionExtractor:
    """Extracts text from regions relative to anchors."""
    
    @staticmethod
    def find_anchor(words: List[Word], target: str, fuzzy_threshold: float = 85) -> Optional[AnchorMatch]:
        """
        Find the best matching anchor using fuzzy string matching.
        
        Args:
            words: List of words to search through
            target: Target text to find
            fuzzy_threshold: Minimum confidence score (0-100)
        
        Returns:
            AnchorMatch if found, None otherwise
        """
        best_match = None
        best_confidence = 0
        
        for word in words:
            # Try exact match first
            if word.text.lower() == target.lower():
                return AnchorMatch(word, 100.0, target)
            
            # Try partial ratio (substring match)
            confidence = fuzz.partial_ratio(word.text.lower(), target.lower())
            
            if confidence > best_confidence and confidence >= fuzzy_threshold:
                best_confidence = confidence
                best_match = AnchorMatch(word, confidence, target)
        
        return best_match
    
    @staticmethod
    def extract_box_region(page: PageData, anchor: AnchorMatch, 
                          dx1: float, dy1: float, dx2: float, dy2: float) -> str:
        """
        Extract text from a box region relative to an anchor.
        
        Args:
            page: Page data containing words
            anchor: Found anchor match
            dx1, dy1: Top-left offset from anchor
            dx2, dy2: Bottom-right offset from anchor
        
        Returns:
            Extracted text from the region
        """
        # Calculate absolute coordinates
        x0 = anchor.word.x0 + dx1
        y0 = anchor.word.y0 + dy1
        x1 = anchor.word.x1 + dx2
        y1 = anchor.word.y1 + dy2
        
        # Get words in the region
        words_in_region = page.get_words_in_region(x0, y0, x1, y1)
        
        # Sort by position (top to bottom, left to right)
        words_in_region.sort(key=lambda w: (w.y0, w.x0))
        
        # Join words with spaces
        return ' '.join(word.text for word in words_in_region).strip()
    
    @staticmethod
    def extract_right_line(page: PageData, anchor: AnchorMatch, 
                          max_distance: float = 200) -> str:
        """
        Extract text to the right of an anchor on the same line.
        
        Args:
            page: Page data containing words
            anchor: Found anchor match
            max_distance: Maximum distance to search right
        
        Returns:
            Text found to the right of the anchor
        """
        # Get words on the same line
        line_words = page.get_words_on_line(anchor.word.y0, tolerance=2.0)
        
        # Filter words to the right of the anchor
        right_words = [
            word for word in line_words
            if word.x0 > anchor.word.x1 and 
               (word.x0 - anchor.word.x1) <= max_distance
        ]
        
        # Sort by x position
        right_words.sort(key=lambda w: w.x0)
        
        # Join words with spaces
        return ' '.join(word.text for word in right_words).strip()
    
    @staticmethod
    def find_nearest_word(words: List[Word], anchor: AnchorMatch, 
                         direction: str = "right", max_distance: float = 100) -> Optional[Word]:
        """
        Find the nearest word in a specific direction from an anchor.
        
        Args:
            words: List of words to search
            anchor: Reference anchor
            direction: "right", "left", "up", "down"
            max_distance: Maximum distance to search
        
        Returns:
            Nearest word if found, None otherwise
        """
        anchor_word = anchor.word
        nearest = None
        min_distance = float('inf')
        
        for word in words:
            if word == anchor_word:
                continue
            
            # Calculate distance based on direction
            if direction == "right":
                if word.x0 > anchor_word.x1 and word.y0 <= anchor_word.y1 + 5 and word.y0 >= anchor_word.y0 - 5:
                    distance = word.x0 - anchor_word.x1
                else:
                    continue
            elif direction == "left":
                if word.x1 < anchor_word.x0 and word.y0 <= anchor_word.y1 + 5 and word.y0 >= anchor_word.y0 - 5:
                    distance = anchor_word.x0 - word.x1
                else:
                    continue
            elif direction == "down":
                if word.y0 > anchor_word.y1 and abs(word.x0 - anchor_word.x0) <= 50:
                    distance = word.y0 - anchor_word.y1
                else:
                    continue
            elif direction == "up":
                if word.y1 < anchor_word.y0 and abs(word.x0 - anchor_word.x0) <= 50:
                    distance = anchor_word.y0 - word.y1
                else:
                    continue
            else:
                continue
            
            if distance <= max_distance and distance < min_distance:
                min_distance = distance
                nearest = word
        
        return nearest


def find_anchors_in_page(page: PageData, targets: List[str], 
                        fuzzy_threshold: float = 85) -> Dict[str, AnchorMatch]:
    """
    Find multiple anchors in a page.
    
    Args:
        page: Page data to search
        targets: List of target strings to find
        fuzzy_threshold: Minimum confidence score
    
    Returns:
        Dictionary mapping target strings to AnchorMatch objects
    """
    results = {}
    
    for target in targets:
        match = RegionExtractor.find_anchor(page.words, target, fuzzy_threshold)
        if match:
            results[target] = match
            logger.debug(f"Found anchor '{target}' with confidence {match.confidence:.1f}")
        else:
            logger.warning(f"Anchor '{target}' not found on page {page.page_num}")
    
    return results


def extract_field_value(page: PageData, field_config: Dict[str, Any], 
                       statement_year: int) -> Optional[str]:
    """
    Extract a field value based on configuration.
    
    Args:
        page: Page data to extract from
        field_config: Field configuration from YAML
        statement_year: Year for date parsing
    
    Returns:
        Extracted field value or None
    """
    find_text = field_config.get('find')
    if not find_text:
        return None
    
    # Find the anchor
    anchor = RegionExtractor.find_anchor(
        page.words, 
        find_text, 
        field_config.get('fuzzy_threshold', 85)
    )
    
    if not anchor:
        return None
    
    # Extract based on strategy
    strategy = field_config.get('strategy', 'box')
    
    if strategy == 'right_line':
        value = RegionExtractor.extract_right_line(page, anchor)
    elif strategy == 'box':
        box = field_config.get('box', {})
        value = RegionExtractor.extract_box_region(
            page, anchor,
            box.get('dx1', 0), box.get('dy1', 0),
            box.get('dx2', 100), box.get('dy2', 20)
        )
    else:
        logger.warning(f"Unknown extraction strategy: {strategy}")
        return None
    
    return value if value else None