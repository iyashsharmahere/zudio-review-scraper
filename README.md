# Zudio Review Scraper Skeleton

1. Create virtual environment.
2. `pip install -r requirements.txt`
3. Copy `.env.example` to `.env`.
4. Implement Selenium logic in `scraper.py`.
5. Call `upsert_review()` for each extracted review.
6. Run `python export.py` after scraping to generate JSON/CSV.
