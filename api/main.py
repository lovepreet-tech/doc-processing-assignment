"""FastAPI app factory. Run with: uvicorn api.main:app --reload"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import batches, conflicts, extractions, files, sessions

app = FastAPI(title="Valuation Extraction API")

# allows the Vite frontend (port 5173) to call this API directly
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(sessions.router)
app.include_router(batches.router)
app.include_router(files.router)
app.include_router(extractions.router)
app.include_router(conflicts.router)


@app.get("/health")
def health():
    return {"status": "ok"}
