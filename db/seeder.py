import subprocess
import sys

def run_step(command, step_name):
    print(f"\n🚀 Running: {step_name}")
    result = subprocess.run(command, shell=True)

    if result.returncode != 0:
        print(f"❌ Failed at: {step_name}")
        sys.exit(1)

    print(f"✅ Completed: {step_name}")

if __name__ == "__main__":
    # Step 1: Setup DB / Index
    run_step("python db/database.py", "Initialize Database")

    # Step 2: Run historical scraper
    run_step("python -m scraper.historical_scraper", "Historical Scraper")

    print("\n🎉 Seeding completed successfully!")