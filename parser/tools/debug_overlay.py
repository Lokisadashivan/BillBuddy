"""
Debug overlay tool for visual QA of PDF parsing.
"""
from pathlib import Path
from typing import List, Dict, Any, Tuple
import logging
from PIL import Image, ImageDraw, ImageFont
import fitz  # PyMuPDF

from ..core.loader import PDFLoader
from ..core.detectors import TemplateDetector
from ..core.anchors import RegionExtractor

logger = logging.getLogger(__name__)


class DebugOverlay:
    """Creates visual debug overlays for PDF parsing."""
    
    def __init__(self, pdf_path: Path, template_id: str):
        self.pdf_path = pdf_path
        self.template_id = template_id
        
        # Load template
        detector = TemplateDetector()
        self.template = detector.get_template(template_id)
        if not self.template:
            raise ValueError(f"Template not found: {template_id}")
        
        # Load PDF
        self.loader = PDFLoader(pdf_path)
        self.pages = self.loader.load()
        
        # Load PDF with PyMuPDF for rendering
        self.pdf_doc = fitz.open(str(pdf_path))
    
    def create_overlays(self, output_dir: Path):
        """
        Create debug overlay images for all pages.
        
        Args:
            output_dir: Directory to save overlay images
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        
        for i, page_data in enumerate(self.pages):
            page_num = page_data.page_num
            
            # Render PDF page to image
            pdf_page = self.pdf_doc[page_num - 1]
            mat = fitz.Matrix(2.0, 2.0)  # 2x zoom for better visibility
            pix = pdf_page.get_pixmap(matrix=mat)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            
            # Create overlay
            overlay = self._create_page_overlay(page_data, img.size)
            
            # Combine images
            combined = Image.alpha_composite(img.convert("RGBA"), overlay)
            
            # Save image
            output_path = output_dir / f"page_{page_num:02d}_overlay.png"
            combined.save(output_path)
            logger.info(f"Created overlay: {output_path}")
    
    def _create_page_overlay(self, page_data, img_size: Tuple[int, int]) -> Image.Image:
        """
        Create overlay for a single page.
        
        Args:
            page_data: PageData object
            img_size: Size of the base image (width, height)
        
        Returns:
            Overlay image with annotations
        """
        # Create transparent overlay
        overlay = Image.new("RGBA", img_size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay)
        
        # Scale factor (PDF coordinates to image coordinates)
        scale_x = img_size[0] / page_data.width
        scale_y = img_size[1] / page_data.height
        
        # Draw word bounding boxes
        self._draw_word_boxes(draw, page_data.words, scale_x, scale_y)
        
        # Draw field extraction boxes
        self._draw_field_boxes(draw, page_data, scale_x, scale_y)
        
        # Draw table columns
        self._draw_table_columns(draw, page_data, scale_x, scale_y)
        
        # Draw anchors
        self._draw_anchors(draw, page_data, scale_x, scale_y)
        
        return overlay
    
    def _draw_word_boxes(self, draw: ImageDraw.Draw, words: List, scale_x: float, scale_y: float):
        """Draw bounding boxes around all words."""
        for word in words:
            x0 = int(word.x0 * scale_x)
            y0 = int(word.y0 * scale_y)
            x1 = int(word.x1 * scale_x)
            y1 = int(word.y1 * scale_y)
            
            # Draw word box in light blue
            draw.rectangle([x0, y0, x1, y1], outline=(0, 150, 255, 128), width=1)
            
            # Draw word text
            try:
                font = ImageFont.truetype("arial.ttf", 8)
            except:
                font = ImageFont.load_default()
            
            draw.text((x0, y0 - 10), word.text[:20], fill=(0, 150, 255, 200), font=font)
    
    def _draw_field_boxes(self, draw: ImageDraw.Draw, page_data, scale_x: float, scale_y: float):
        """Draw boxes for field extraction areas."""
        fields_config = self.template.get('fields', {})
        
        for field_name, field_config in fields_config.items():
            find_text = field_config.get('find')
            if not find_text:
                continue
            
            # Find anchor
            anchor = RegionExtractor.find_anchor(page_data.words, find_text, 85)
            if not anchor:
                continue
            
            # Draw anchor
            x0 = int(anchor.word.x0 * scale_x)
            y0 = int(anchor.word.y0 * scale_y)
            x1 = int(anchor.word.x1 * scale_x)
            y1 = int(anchor.word.y1 * scale_y)
            
            draw.rectangle([x0, y0, x1, y1], outline=(255, 0, 0, 200), width=2)
            
            # Draw extraction box if specified
            box = field_config.get('box')
            if box:
                dx1 = box.get('dx1', 0)
                dy1 = box.get('dy1', 0)
                dx2 = box.get('dx2', 100)
                dy2 = box.get('dy2', 20)
                
                box_x0 = int((anchor.word.x0 + dx1) * scale_x)
                box_y0 = int((anchor.word.y0 + dy1) * scale_y)
                box_x1 = int((anchor.word.x1 + dx2) * scale_x)
                box_y1 = int((anchor.word.y1 + dy2) * scale_y)
                
                draw.rectangle([box_x0, box_y0, box_x1, box_y1], 
                             outline=(0, 255, 0, 200), width=2)
                
                # Label the field
                try:
                    font = ImageFont.truetype("arial.ttf", 10)
                except:
                    font = ImageFont.load_default()
                
                draw.text((box_x0, box_y0 - 15), field_name, 
                         fill=(0, 255, 0, 255), font=font)
    
    def _draw_table_columns(self, draw: ImageDraw.Draw, page_data, scale_x: float, scale_y: float):
        """Draw table column boundaries."""
        transactions_config = self.template.get('transactions', {})
        columns = transactions_config.get('columns', [])
        
        if not columns:
            return
        
        # Find table header
        header_config = transactions_config.get('header', {})
        labels = header_config.get('label', [])
        
        if not labels:
            return
        
        # Find first header label to get table position
        first_label = labels[0]
        anchor = RegionExtractor.find_anchor(page_data.words, first_label, 80)
        if not anchor:
            return
        
        # Draw column boundaries
        table_y_start = int(anchor.word.y0 * scale_y)
        table_y_end = int(page_data.height * scale_y)
        
        for col in columns:
            x = int(col['x1'] * scale_x)
            draw.line([x, table_y_start, x, table_y_end], 
                     fill=(255, 255, 0, 200), width=2)
            
            # Label the column
            try:
                font = ImageFont.truetype("arial.ttf", 10)
            except:
                font = ImageFont.load_default()
            
            draw.text((x + 2, table_y_start - 20), col['name'], 
                     fill=(255, 255, 0, 255), font=font)
    
    def _draw_anchors(self, draw: ImageDraw.Draw, page_data, scale_x: float, scale_y: float):
        """Draw all found anchors."""
        page_match = self.template.get('page_match', {})
        must_contain = page_match.get('must_contain', [])
        
        for anchor_text in must_contain:
            anchor = RegionExtractor.find_anchor(page_data.words, anchor_text, 85)
            if anchor:
                x0 = int(anchor.word.x0 * scale_x)
                y0 = int(anchor.word.y0 * scale_y)
                x1 = int(anchor.word.x1 * scale_x)
                y1 = int(anchor.word.y1 * scale_y)
                
                # Draw anchor box in red
                draw.rectangle([x0, y0, x1, y1], outline=(255, 0, 0, 200), width=3)
                
                # Label the anchor
                try:
                    font = ImageFont.truetype("arial.ttf", 12)
                except:
                    font = ImageFont.load_default()
                
                draw.text((x0, y0 - 25), f"ANCHOR: {anchor_text}", 
                         fill=(255, 0, 0, 255), font=font)
    
    def close(self):
        """Close resources."""
        if hasattr(self, 'loader'):
            self.loader.close()
        if hasattr(self, 'pdf_doc'):
            self.pdf_doc.close()


def create_debug_overlay(pdf_path: Path, template_id: str, output_dir: Path):
    """
    Create debug overlay images for a PDF.
    
    Args:
        pdf_path: Path to PDF file
        template_id: Template ID to use
        output_dir: Directory to save overlay images
    """
    overlay = DebugOverlay(pdf_path, template_id)
    try:
        overlay.create_overlays(output_dir)
    finally:
        overlay.close()