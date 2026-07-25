from fastapi import FastAPI
from backend.app import app as backend_app

app = FastAPI()

@app.get("/")
async def root():
    return {"message": "ClimateJobsPortal is running"}
