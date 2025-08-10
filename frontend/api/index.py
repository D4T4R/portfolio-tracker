# frontend/api/index.py
import os, sys

# Allow importing the backend package from repo root
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
REPO_ROOT = os.path.abspath(os.path.join(FRONTEND_DIR, ".."))
sys.path.append(REPO_ROOT)

# Import your existing Flask app (app = Flask(__name__) in backend/app.py)
from backend.app import app  # <-- expose 'app' directly for Vercel