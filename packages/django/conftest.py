import sys
from pathlib import Path

# Ensure both src/ and the project root (for tests/) are on the path
root = Path(__file__).parent
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / "src"))
