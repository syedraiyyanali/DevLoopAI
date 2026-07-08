from fastapi import FastAPI

app = FastAPI(
    title="DevLoopAI",
    description="Local Autonomous AI Development Platform",
    version="0.1.0",
)


@app.get("/")
async def root():
    return {
        "application": "DevLoopAI",
        "status": "running",
        "version": "0.1.0",
    }


@app.get("/health")
async def health():
    return {
        "status": "healthy",
    }