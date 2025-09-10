#!/bin/bash
# Database Reset Helper Script

echo "🗄️  Database Reset Configuration"
echo "=================================="

# Check current setting
if [ "$RESET_DATABASE" = "true" ]; then
    echo "Current setting: RESET_DATABASE=true (Database will be completely reset on startup)"
else
    echo "Current setting: RESET_DATABASE=false (Only data will be cleared, tables kept)"
fi

echo ""
echo "Options:"
echo "1. Enable complete database reset (drop all tables)"
echo "2. Disable complete database reset (keep table structure)"
echo "3. Start server with current setting"
echo "4. Exit"

read -p "Choose option (1-4): " choice

case $choice in
    1)
        export RESET_DATABASE=true
        echo "✅ Set RESET_DATABASE=true"
        echo "🚀 Starting server with complete database reset..."
        uvicorn main:app --reload --port 8000
        ;;
    2)
        export RESET_DATABASE=false
        echo "✅ Set RESET_DATABASE=false"
        echo "🚀 Starting server with data clearing only..."
        uvicorn main:app --reload --port 8000
        ;;
    3)
        echo "🚀 Starting server with current setting..."
        uvicorn main:app --reload --port 8000
        ;;
    4)
        echo "👋 Goodbye!"
        exit 0
        ;;
    *)
        echo "❌ Invalid option"
        exit 1
        ;;
esac
