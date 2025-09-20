# BillBuddy PDF Parser - Anchor & Coordinates (A&C) Method

This document describes the new PDF parsing technique implemented for Standard Chartered eStatements using the Anchor & Coordinates (A&C) approach.

## Overview

The new parsing system replaces the previous regex-based text extraction with a more robust, deterministic approach that uses:

- **pdfplumber** for precise word positioning and text extraction
- **Camelot** as fallback for table extraction
- **RapidFuzz** for fuzzy anchor matching
- **Pydantic** for data validation
- **YAML templates** for configuration-driven parsing

## Architecture

```
parser/
├── app.py                    # CLI interface
├── core/
│   ├── loader.py            # PDF loading and word extraction
│   ├── anchors.py           # Anchor finding and region extraction
│   ├── tables.py            # Table extraction with fallback
│   ├── normalize.py         # Data cleaning and normalization
│   ├── detectors.py         # Template detection
│   └── runner.py            # End-to-end orchestration
├── templates/
│   └── scb_smart_v1.yaml    # Standard Chartered template
├── models/
│   └── schema.py            # Pydantic data models
├── tools/
│   └── debug_overlay.py     # Visual debugging tool
└── tests/
    └── test_scb_smart_v1.py # Test suite
```

## Key Features

### 1. Anchor-Based Field Extraction
- Uses fuzzy string matching to find anchor text
- Extracts data from relative coordinate boxes
- Supports multiple extraction strategies (box, right-line, nearest-word)

### 2. Deterministic Table Parsing
- Clusters words into rows based on vertical position
- Assigns text to columns using x-coordinate bands
- Handles wrapped descriptions and reference lines
- Camelot fallback for complex table layouts

### 3. Template-Driven Configuration
- YAML templates define parsing rules
- Easy to adapt for different statement formats
- Configurable column positions and extraction strategies

### 4. Robust Data Validation
- Pydantic models ensure data integrity
- Balance equation validation
- Type checking and format validation

## Usage

### CLI Interface
```bash
# Parse a PDF
python -m parser.app parse ./samples/statement.pdf --out result.json

# Detect template
python -m parser.app detect ./samples/statement.pdf

# Validate JSON
python -m parser.app validate ./result.json
```

### Python API
```python
from parser import parse_statement, detect_template

# Detect and parse
template = detect_template("statement.pdf")
result = parse_statement("statement.pdf", template)

# Access structured data
print(f"Statement date: {result.meta.statement_date}")
print(f"Transactions: {len(result.transactions)}")
print(f"New balance: {result.summary.new_balance}")
```

### Backend API
```bash
# Start backend server
cd backend
python main.py

# Parse via HTTP API
curl -X POST "http://localhost:8000/parse" \
  -F "file=@statement.pdf" \
  -F "template=scb_smart_v1"
```

## Template Configuration

The YAML template defines:

```yaml
template_id: scb_smart_v1
bank: "Standard Chartered Bank (Singapore)"

page_match:
  must_contain:
    - "Credit Card and Personal Loan Statement"
    - "Statement Date"
  fuzzy_threshold: 85

fields:
  statement_date:
    page: 1
    find: "Statement Date"
    box: {dx1: 120, dy1: -6, dx2: 320, dy2: 22}
    post: date:%d %b %Y

transactions:
  header:
    label: ["Transaction", "Posting", "Description", "Amount (SGD)"]
  columns:
    - {name: "transaction_date", x1: 40, x2: 110, type: "date:%d %b"}
    - {name: "amount", x1: 470, x2: 560, type: "money:paren_or_cr"}
```

## Data Output

The parser outputs structured JSON with:

```json
{
  "meta": {
    "bank": "Standard Chartered Bank (Singapore)",
    "template_id": "scb_smart_v1",
    "statement_date": "2025-08-17",
    "card_masked": "4864-18XX-XXXX-1669"
  },
  "summary": {
    "previous_balance": 1825.21,
    "new_balance": 1783.31,
    "minimum_payment_due": 50.00
  },
  "transactions": [
    {
      "transaction_date": "2025-07-17",
      "description": "CHEERS - PARKLANE S SINGAPORE SG",
      "amount": 10.00,
      "currency": "SGD",
      "reference": "74508985217021376353487",
      "type": "purchase"
    }
  ],
  "instalments": [...],
  "rewards": {...}
}
```

## Debugging

### Visual Debug Overlay
```bash
python -m parser.app parse statement.pdf --debug-overlay ./debug/
```

Creates PNG images with:
- Word bounding boxes
- Field extraction regions
- Table column boundaries
- Anchor positions

### Logging
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## Testing

```bash
# Run test suite
cd parser
python -m pytest tests/

# Test with sample PDF
python -m pytest tests/test_scb_smart_v1.py -v
```

## Performance

- **Memory safe**: Handles PDFs up to 30 pages
- **Fast parsing**: < 2 seconds for typical statements
- **No network calls**: Fully offline operation
- **Robust**: Handles text variations and layout changes

## Integration with Frontend

The React frontend now uses the Python backend:

1. **Upload PDF** → Frontend sends to backend API
2. **Parse with A&C** → Backend uses new parsing technique
3. **Return structured data** → Frontend receives validated JSON
4. **Fallback handling** → Falls back to mock data if backend unavailable

## Migration from Old Parser

The new system is backward compatible:
- Frontend automatically tries new backend first
- Falls back to old parsing if backend unavailable
- Same data format for seamless integration
- Enhanced accuracy and reliability

## Future Enhancements

- Support for additional bank templates
- OCR integration for scanned PDFs
- Machine learning for template detection
- Real-time parsing status updates
- Batch processing capabilities