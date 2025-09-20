"""
Template detection and validation.
"""
import yaml
from pathlib import Path
from typing import Dict, Any, Optional, List
import logging

from .loader import PDFLoader
from .anchors import find_anchors_in_page

logger = logging.getLogger(__name__)


class TemplateDetector:
    """Detects which template matches a PDF file."""
    
    def __init__(self, templates_dir: Path = None):
        self.templates_dir = templates_dir or Path(__file__).parent.parent / "templates"
        self.templates = {}
        self._load_templates()
    
    def _load_templates(self):
        """Load all available templates."""
        if not self.templates_dir.exists():
            logger.warning(f"Templates directory not found: {self.templates_dir}")
            return
        
        for yaml_file in self.templates_dir.glob("*.yaml"):
            try:
                with open(yaml_file, 'r', encoding='utf-8') as f:
                    template_data = yaml.safe_load(f)
                    template_id = template_data.get('template_id')
                    if template_id:
                        self.templates[template_id] = template_data
                        logger.debug(f"Loaded template: {template_id}")
            except Exception as e:
                logger.error(f"Error loading template {yaml_file}: {e}")
    
    def detect_template(self, pdf_path: Path) -> Optional[str]:
        """
        Detect which template matches the PDF.
        
        Args:
            pdf_path: Path to PDF file
        
        Returns:
            Template ID if found, None otherwise
        """
        try:
            loader = PDFLoader(pdf_path)
            pages = loader.load()
            
            if not pages:
                logger.error("No pages found in PDF")
                return None
            
            # Check each template
            for template_id, template_config in self.templates.items():
                if self._matches_template(pages, template_config):
                    logger.info(f"PDF matches template: {template_id}")
                    return template_id
            
            logger.warning("No matching template found")
            return None
            
        except Exception as e:
            logger.error(f"Error detecting template: {e}")
            return None
        finally:
            if 'loader' in locals():
                loader.close()
    
    def _matches_template(self, pages: List, template_config: Dict[str, Any]) -> bool:
        """
        Check if pages match a template configuration.
        
        Args:
            pages: List of PageData objects
            template_config: Template configuration
        
        Returns:
            True if template matches, False otherwise
        """
        page_match = template_config.get('page_match', {})
        must_contain = page_match.get('must_contain', [])
        fuzzy_threshold = page_match.get('fuzzy_threshold', 85)
        
        if not must_contain:
            logger.warning("Template has no 'must_contain' requirements")
            return False
        
        # Check each page for required content
        for page in pages:
            found_anchors = find_anchors_in_page(page, must_contain, fuzzy_threshold)
            
            # If we find all required anchors on any page, template matches
            if len(found_anchors) == len(must_contain):
                logger.debug(f"All required anchors found on page {page.page_num}")
                return True
        
        logger.debug(f"Template mismatch: found {len(found_anchors)}/{len(must_contain)} required anchors")
        return False
    
    def get_template(self, template_id: str) -> Optional[Dict[str, Any]]:
        """Get template configuration by ID."""
        return self.templates.get(template_id)
    
    def list_templates(self) -> List[str]:
        """List all available template IDs."""
        return list(self.templates.keys())


def detect_template(pdf_path: Path) -> Optional[str]:
    """
    Convenience function to detect template for a PDF.
    
    Args:
        pdf_path: Path to PDF file
    
    Returns:
        Template ID if found, None otherwise
    """
    detector = TemplateDetector()
    return detector.detect_template(pdf_path)


def validate_template_match(pdf_path: Path, template_id: str) -> bool:
    """
    Validate that a PDF matches a specific template.
    
    Args:
        pdf_path: Path to PDF file
        template_id: Template ID to validate against
    
    Returns:
        True if PDF matches template, False otherwise
    """
    detector = TemplateDetector()
    template = detector.get_template(template_id)
    
    if not template:
        logger.error(f"Template not found: {template_id}")
        return False
    
    try:
        loader = PDFLoader(pdf_path)
        pages = loader.load()
        
        if not pages:
            return False
        
        return detector._matches_template(pages, template)
        
    except Exception as e:
        logger.error(f"Error validating template match: {e}")
        return False
    finally:
        if 'loader' in locals():
            loader.close()