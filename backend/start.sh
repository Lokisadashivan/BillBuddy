#!/bin/bash
# Start the BillBuddy PDF Parser backend

echo "Starting BillBuddy PDF Parser Backend..."

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is required but not installed."
    exit 1
fi

# Check if we're in the right directory
if [ ! -f "main.py" ]; then
    echo "Error: main.py not found. Please run this script from the backend directory."
    exit 1
fi

# Install dependencies if requirements.txt exists
if [ -f "requirements.txt" ]; then
    echo "Installing Python dependencies..."
    pip3 install -r requirements.txt
fi

# Install parser dependencies
if [ -f "../parser/requirements.txt" ]; then
    echo "Installing parser dependencies..."
    pip3 install -r ../parser/requirements.txt
fi

# Start the server
echo "Starting FastAPI server on http://localhost:8000"
echo "API documentation available at http://localhost:8000/docs"
echo "Press Ctrl+C to stop the server"
echo ""

python3 main.py