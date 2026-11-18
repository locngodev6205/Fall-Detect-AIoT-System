"""Select the configured persistence backend at process startup."""
import os
backend=os.getenv("DATABASE_BACKEND", "postgres").lower()
if backend=="postgres":
    from .pgmain import app
elif backend=="sqlite":
    from .main import app
else:
    raise RuntimeError("DATABASE_BACKEND phải là postgres hoặc sqlite.")
