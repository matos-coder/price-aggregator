import logging
import subprocess
from fastapi import FastAPI, BackgroundTasks

# Set up logging so we can see the health checks in Hugging Face Logs
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("HealthServer")

app = FastAPI()

@app.get("/")
@app.get("/health")
def health_check():
    """Hugging Face will hit this constantly. We log it so you know it works."""
    logger.info("✅ Hugging Face Health Check Ping Received!")
    return {"status": "ok", "message": "Ethio Price Radar is running smoothly."}

def run_seeder_script():
    """This function actually runs your seeder in the terminal."""
    logger.info("🌱 Seeder initialized. Scraping historical data...")
    try:
        # Runs python -m db.seeder just like you would in the terminal
        subprocess.run(["python", "-m", "db.seeder"], check=True)
        logger.info("🌲 Seeder finished successfully!")
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ Seeder crashed: {e}")

@app.post("/trigger-seeder")
def trigger_seeder(background_tasks: BackgroundTasks):
    """
    You can hit this endpoint via Postman or cURL to start the seeder 
    in the background without freezing the health check server.
    """
    logger.info("Received external request to run seeder.")
    background_tasks.add_task(run_seeder_script)
    return {"status": "Seeder started in the background. Check logs for progress."}
