

echo "================================"
echo "XXAR - GUI Launcher"
echo "================================"
echo ""

if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found. Please install Python 3."
    exit 1
fi
echo "✓ Python 3 found"

if ! python3 -c "import PyQt6" 2>/dev/null; then
    echo "❌ PyQt6 not found"
    echo ""
    echo "Installing PyQt6..."

    if command -v pacman &> /dev/null; then
        sudo pacman -S --needed python-pyqt6
    elif command -v apt &> /dev/null; then
        sudo apt install python3-pyqt6 python3-pyqt6.qtquick python3-pyqt6.qtmultimedia
    elif command -v dnf &> /dev/null; then
        sudo dnf install python3-pyqt6
    else
        echo "Please install PyQt6 for your distribution"
        echo "Or use: pip install PyQt6"
        exit 1
    fi
fi
echo "✓ PyQt6 found"

if ! python3 -c "from PyQt6.QtQml import QQmlApplicationEngine" 2>/dev/null; then
    echo "⚠️  PyQt6.QtQml not found"
    echo ""
    echo "The QML UI requires PyQt6 with QML support."
    echo "Please install the full PyQt6 package or run:"
    echo "  pip install PyQt6"
    echo ""
    exit 1
fi
echo "✓ PyQt6.QtQml found"

echo ""
echo "Starting XXAR GUI..."
echo ""

cd "$(dirname "$0")"
python3 XXAR.py

echo ""
echo "GUI closed."
