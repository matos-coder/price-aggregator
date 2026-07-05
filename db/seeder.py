import subprocess
import sys

def run_step(module, step_name):
    print(f"\n🚀 Running: {step_name}")
    # sys.executable + -m keeps package-relative imports working and avoids
    # depending on whatever 'python' happens to be on PATH.
    result = subprocess.run([sys.executable, "-m", module])

    if result.returncode != 0:
        print(f"❌ Failed at: {step_name}")
        sys.exit(1)

    print(f"✅ Completed: {step_name}")

if __name__ == "__main__":
    # Step 1: Setup DB / Index
    run_step("db.database", "Initialize Database")

    # Step 2: Run historical scraper
    run_step("scraper.historical_scraper", "Historical Scraper")

    print("\n🎉 Seeding completed successfully!")
