"""Select the configured persistence backend at process startup."""
import os
if os.getenv("DATABASE_BACKEND", "sqlite")=="postgres":
    from .pgmain import app
else:
    from .main import app
