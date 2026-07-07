from fastapi import FastAPI
from scraper import run_scraper
from database import get_reviews

app = FastAPI(
    title="Zudio Review Scraper",
    version="1.0.0"
)

@app.get("/")
def home():
    return {
        "message": "Zudio Review Scraper API"
    }

@app.post("/scrape")
def scrape_reviews():
    result = run_scraper()
    return result

@app.get("/reviews")
def reviews():
    return get_reviews()