"""
FastAPI backend service for PDF parsing.
"""
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import tempfile
import shutil
from pathlib import Path
import logging
from typing import Dict, Any

# Import our parser
import sys
sys.path.append(str(Path(__file__).parent.parent / "parser"))
from parser import parse_statement, detect_template

app = FastAPI(title="BillBuddy PDF Parser", version="1.0.0")

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],  # Vite and other dev servers
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@app.get("/")
async def root():
    """Health check endpoint."""
    return {"message": "BillBuddy PDF Parser API", "status": "healthy"}


@app.post("/parse")
async def parse_pdf(file: UploadFile = File(...), template: str = "scb_smart_v1"):
    """
    Parse a PDF file and return structured data.
    
    Args:
        file: Uploaded PDF file
        template: Template ID to use (default: scb_smart_v1)
    
    Returns:
        Parsed statement data as JSON
    """
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="File must be a PDF")
    
    # Create temporary file
    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
        try:
            # Save uploaded file to temporary location
            shutil.copyfileobj(file.file, tmp_file)
            tmp_path = Path(tmp_file.name)
            
            logger.info(f"Processing PDF: {file.filename}")
            
            # Detect template if not specified
            if template == "auto":
                detected_template = detect_template(tmp_path)
                if not detected_template:
                    raise HTTPException(status_code=400, detail="Could not detect template for this PDF")
                template = detected_template
                logger.info(f"Detected template: {template}")
            
            # Parse the PDF
            result = parse_statement(tmp_path, template, verbose=True)
            
            # Convert to dict for JSON response
            data = result.model_dump()
            
            logger.info(f"Successfully parsed PDF: {len(data['transactions'])} transactions found")
            
            return JSONResponse(content={
                "success": True,
                "data": data,
                "template_used": template,
                "summary": {
                    "transactions_count": len(data['transactions']),
                    "instalments_count": len(data['instalments']),
                    "statement_date": str(data['meta']['statement_date']),
                    "new_balance": float(data['summary']['new_balance'])
                }
            })
            
        except Exception as e:
            logger.error(f"Error parsing PDF: {e}")
            raise HTTPException(status_code=500, detail=f"Error parsing PDF: {str(e)}")
        
        finally:
            # Clean up temporary file
            if tmp_path.exists():
                tmp_path.unlink()


@app.post("/detect-template")
async def detect_pdf_template(file: UploadFile = File(...)):
    """
    Detect which template matches a PDF file.
    
    Args:
        file: Uploaded PDF file
    
    Returns:
        Detected template ID
    """
    if not file.filename.lower().endswith('.pdf'):
        raise HTTPException(status_code=400, detail="File must be a PDF")
    
    with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as tmp_file:
        try:
            shutil.copyfileobj(file.file, tmp_file)
            tmp_path = Path(tmp_file.name)
            
            template = detect_template(tmp_path)
            
            if not template:
                raise HTTPException(status_code=400, detail="No matching template found")
            
            return JSONResponse(content={
                "success": True,
                "template": template
            })
            
        except Exception as e:
            logger.error(f"Error detecting template: {e}")
            raise HTTPException(status_code=500, detail=f"Error detecting template: {str(e)}")
        
        finally:
            if tmp_path.exists():
                tmp_path.unlink()


@app.get("/templates")
async def list_templates():
    """List all available templates."""
    # This would be implemented to read from the templates directory
    return JSONResponse(content={
        "success": True,
        "templates": [
            {
                "id": "scb_smart_v1",
                "name": "Standard Chartered Smart Credit Card",
                "bank": "Standard Chartered Bank (Singapore)",
                "description": "Template for Standard Chartered Smart Credit Card statements"
            }
        ]
    })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)