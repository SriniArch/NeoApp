import sys
import os

# Ensure project root is in path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Run the scalper module directly since it has the UI code in its global scope
import scalper.neoscalper