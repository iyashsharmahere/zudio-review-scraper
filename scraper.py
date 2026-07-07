
import logging
import os
import re
import time
from datetime import datetime, timezone, timedelta
from functools import wraps
from logging.handlers import RotatingFileHandler
from typing import Callable, Dict, List, Optional

from dotenv import load_dotenv
from selenium import webdriver
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

# Load environment variables from .env
load_dotenv()

# ---------------------------------------------------------------------------
# Logging configuration
# ---------------------------------------------------------------------------
os.makedirs("logs", exist_ok=True)

logger = logging.getLogger("zudio.scraper")
logger.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s", "%Y-%m-%d %H:%M:%S")

# Console handler
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# Rotating file handler (5MB per file, 3 backups)
file_handler = RotatingFileHandler(
    "logs/scraper.log", maxBytes=5*1024*1024, backupCount=3, encoding="utf-8"
)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# ---------------------------------------------------------------------------
# Configuration (falls back to defaults if not in .env)
# ---------------------------------------------------------------------------
PAGE_LOAD_TIMEOUT = int(os.getenv("PAGE_LOAD_TIMEOUT", 40))
ELEMENT_TIMEOUT = int(os.getenv("ELEMENT_TIMEOUT", 15))
SCROLL_PAUSE = float(os.getenv("SCROLL_PAUSE", 1.2))
MAX_SCROLL_ATTEMPTS = int(os.getenv("MAX_SCROLL_ATTEMPTS", 80))
STALE_THRESHOLD = int(os.getenv("STALE_THRESHOLD", 4))
RETRY_ATTEMPTS = int(os.getenv("RETRY_ATTEMPTS", 3))
RETRY_DELAY = float(os.getenv("RETRY_DELAY", 2.0))

# Comma-separated URLs in .env or fallback to search URL
STORES = [ 
     "https://maps.app.goo.gl/phvgdCjiiRJXRn4x9",
      "https://maps.app.goo.gl/K1et6Xke6rgBkA2B6",
       "https://maps.app.goo.gl/We7vV73JAKEm6jMJ7",
     "https://maps.app.goo.gl/B4VkUU5CeNxCyrPg8",
      "https://maps.app.goo.gl/cnezxgttAbs3SR497" 
]


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------
def retry_on_failure(max_retries: int = RETRY_ATTEMPTS, delay: float = RETRY_DELAY) -> Callable:
    """
    Decorator to retry a function upon transient WebDriver failures.
    
    Parameters
    ----------
    max_retries : int
        Maximum number of attempts before giving up.
    delay : float
        Seconds to wait between retries.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except (TimeoutException, WebDriverException) as exc:
                    last_exception = exc
                    logger.warning(
                        f"Attempt {attempt}/{max_retries} failed for {func.__name__}: {exc}"
                    )
                    if attempt < max_retries:
                        time.sleep(delay)
            logger.error(f"Function {func.__name__} failed after {max_retries} attempts.")
            raise last_exception
        return wrapper
    return decorator

def parse_relative_date(date_str: str) -> str:
    """
    Parse a Google Maps relative date string (e.g. '3 days ago', 'a week ago')
    into a calendar date string 'DD-MM-YYYY' based on the current date.
    """
    if not date_str:
        return ""

    date_str_clean = date_str.lower().strip()
    now = datetime.now()

    if date_str_clean in ("today", "just now", "now", "new"):
        return now.strftime("%d-%m-%Y")
    if date_str_clean == "yesterday":
        target_date = now - timedelta(days=1)
        return target_date.strftime("%d-%m-%Y")

    # Match patterns like:
    # "a day ago", "2 days ago", "1 day ago"
    # "a week ago", "3 weeks ago"
    # "a month ago", "6 months ago"
    # "a year ago", "2 years ago"
    # "a minute ago", "5 minutes ago", "an hour ago", "3 hours ago"
    pattern = r"^(a|an|\d+)\s+(minute|hour|day|week|month|year)s?\s+ago$"
    match = re.match(pattern, date_str_clean)
    if match:
        val_str, unit = match.groups()
        if val_str in ("a", "an"):
            val = 1
        else:
            val = int(val_str)

        if unit == "minute":
            target_date = now - timedelta(minutes=val)
        elif unit == "hour":
            target_date = now - timedelta(hours=val)
        elif unit == "day":
            target_date = now - timedelta(days=val)
        elif unit == "week":
            target_date = now - timedelta(weeks=val)
        elif unit == "month":
            # Approximating a month as 30 days
            target_date = now - timedelta(days=val * 30)
        elif unit == "year":
            # Approximating a year as 365 days
            target_date = now - timedelta(days=val * 365)
        else:
            return date_str

        return target_date.strftime("%d-%m-%Y")

    return date_str


# ---------------------------------------------------------------------------
# Driver setup
# ---------------------------------------------------------------------------
def setup_driver() -> webdriver.Chrome:
    """
    Initialise a headless Chrome WebDriver using ChromeDriverManager.
    """
    logger.info("Initialising Chrome WebDriver via ChromeDriverManager.")

    options = Options()
    # options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)

    try:
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"},
        )
    except WebDriverException:
        logger.debug("Could not patch navigator.webdriver flag.")

    logger.info("WebDriver ready.")
    return driver


# ---------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------
@retry_on_failure()
def open_store(driver: webdriver.Chrome, url: str) -> bool:
    """
    Open a single store's Google Maps page with retry logic.
    """
    logger.info("Opening store URL: %s", url)
    driver.get(url)
    WebDriverWait(driver, ELEMENT_TIMEOUT).until(
        EC.presence_of_element_located((By.CSS_SELECTOR, "h1"))
    )
    return True


def get_store_name(driver: webdriver.Chrome) -> str:
    """Return the title of the currently-loaded store."""
    try:
        element = driver.find_element(By.CSS_SELECTOR, "h1")
        name = element.text.strip()
        return name or "Unknown Store"
    except NoSuchElementException:
        logger.warning("Store name element not found.")
        return "Unknown Store"


@retry_on_failure()
def open_reviews(driver: webdriver.Chrome) -> bool:
    """
    Open the reviews panel for the current store.
    Falls back to the 'See all reviews' link or reviews-count widget.
    """
    logger.info("Attempting to open the reviews panel.")

    candidate_selectors = [
    # Reviews tab (new Google Maps)
    (By.XPATH, "//button[normalize-space()='Reviews']"),

    # Reviews tab using role
    (By.XPATH, "//button[@role='tab' and contains(.,'Reviews')]"),

    # href fallback
    (By.CSS_SELECTOR, "a[href*='reviews']"),

    # old review button fallback
    (By.XPATH, "//button[contains(@aria-label,'review')]"),

    (By.XPATH, "//button[contains(@aria-label,'Review')]"),
]

    for by, selector in candidate_selectors:
        try:
            element = WebDriverWait(driver, ELEMENT_TIMEOUT).until(
                EC.element_to_be_clickable((by, selector))
            )
            driver.execute_script("arguments[0].scrollIntoView(true);", element)
            try:
                element.click()
            except ElementClickInterceptedException:
                driver.execute_script("arguments[0].click();", element)
            
            # Wait until the Reviews tab is visible
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located(
                    (By.XPATH, "//button[contains(., 'Reviews')] | //div[text()='Reviews']")
                 )
            )
            reviews_tab = driver.find_element(
                By.XPATH,
                "//button[contains(., 'Reviews') or .//div[text()='Reviews']]"
            )
            driver.execute_script("arguments[0].click();", reviews_tab)

            # Wait until review cards appear
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located(
                    (By.CSS_SELECTOR, "div.jftiEf")
                )
            )
            

            logger.info("Reviews tab opened successfully.")
            return True
        except TimeoutException:
            continue
        except WebDriverException as exc:
            logger.debug("Selector %s failed: %s", selector, exc)
            continue

    logger.error("Could not open the reviews panel.")
    return False


# ---------------------------------------------------------------------------
# Scrolling Logic
# ---------------------------------------------------------------------------
def _get_reviews_scroll_container(driver: webdriver.Chrome) -> Optional[WebElement]:
    """Return the scrollable container that holds the reviews feed."""
    candidates = [
        (By.CSS_SELECTOR, 'div.m6QErb.DxyBCb.kA9KIf.dS8AEf'),
        (By.CSS_SELECTOR, 'div.m6QErb.DxyBCb.XiKgde'),
        (By.CSS_SELECTOR, 'div[role="main"]'),
    ]
    for by, selector in candidates:
        try:
            return driver.find_element(by, selector)
        except NoSuchElementException:
            continue

    logger.warning("Reviews scroll container not found; falling back to <body>.")
    return driver.find_element(By.TAG_NAME, "body")


def scroll_and_extract_reviews(driver: webdriver.Chrome, store_name: str) -> List[Dict[str, str]]:
    """
    Scroll and extract reviews concurrently.
    Extracts visible reviews first, then scrolls, and repeats to handle virtual DOM loading.
    """
    logger.info("Scrolling and extracting reviews concurrently...")

    container = _get_reviews_scroll_container(driver)

    if container is None:
        logger.error("No reviews container found.")
        return []

    reviews: List[Dict[str, str]] = []
    seen_ids = set()
    last_review_id = None
    stale_rounds = 0
    scroll_attempts = 0

    row_selectors = [
        'div[data-review-id]',
        'div.jftiEf',
        'div[jsaction*="mouseover"]:has(div[class*="RfD5qd"])',
    ]

    while stale_rounds < 5 and scroll_attempts < MAX_SCROLL_ATTEMPTS:
        # 1. Find all visible review card elements currently in the DOM
        review_elements: List[WebElement] = []
        for selector in row_selectors:
            try:
                review_elements = container.find_elements(By.CSS_SELECTOR, selector)
                if review_elements:
                    break
            except Exception as exc:
                logger.debug("Selector %s failed during loop: %s", selector, exc)
                continue

        # 2. Extract new reviews in this batch
        new_extracted_count = 0
        for element in review_elements:
            try:
                review_id = element.get_attribute("data-review-id")
            except StaleElementReferenceException:
                continue

            # Deduplicate by review_id if available to avoid redundant work
            if review_id and review_id in seen_ids:
                continue

            review = _extract_single_review(driver, element, store_name)
            if review is None:
                continue

            # Deduplicate key (use review_id or composite of name + start of text)
            dedupe_key = review["review_id"] or (
                review["reviewer_name"] + "|" + review["review_text"][:50]
            )

            if dedupe_key in seen_ids:
                continue

            seen_ids.add(dedupe_key)
            reviews.append(review)
            new_extracted_count += 1

        if new_extracted_count > 0:
            logger.info(f"Extracted {new_extracted_count} new reviews (Total extracted: {len(reviews)})")

        # 3. Track last review card ID before scroll
        try:
            cards = container.find_elements(By.CSS_SELECTOR, "div[data-review-id]")
            current_last = cards[-1].get_attribute("data-review-id") if cards else None
        except (NoSuchElementException, StaleElementReferenceException, IndexError):
            current_last = None

        # 4. Scroll container down
        try:
            driver.execute_script(
                "arguments[0].scrollTop = arguments[0].scrollHeight;",
                container
            )
        except Exception as exc:
            logger.debug("Failed to set scrollTop on container: %s", exc)

        # Also scroll the last visible card into view to trigger lazy loading
        if review_elements:
            try:
                driver.execute_script("arguments[0].scrollIntoView(true);", review_elements[-1])
            except Exception as exc:
                logger.debug("Failed to scroll last card into view: %s", exc)

        scroll_attempts += 1
        time.sleep(SCROLL_PAUSE)

        # 5. Check if new reviews loaded
        try:
            cards = container.find_elements(By.CSS_SELECTOR, "div[data-review-id]")
            new_last = cards[-1].get_attribute("data-review-id") if cards else None
        except (NoSuchElementException, StaleElementReferenceException, IndexError):
            new_last = None

        if new_last == last_review_id:
            stale_rounds += 1
            logger.info(f"No scroll progress: no new reviews loaded ({stale_rounds}/5)")
        else:
            stale_rounds = 0
            last_review_id = new_last
            logger.info(f"Scroll attempt {scroll_attempts}: loaded till review ID: {last_review_id}")

    logger.info("Finished scrolling and extraction. Extracted %d unique reviews.", len(reviews))
    return reviews
# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------
def _parse_rating(label: str) -> Optional[int]:
    """Extract integer rating (1-5) from aria-label string."""
    if not label:
        return None
    match = re.search(r"(\d)", label)
    return int(match.group(1)) if match else None


def _extract_single_review(
    driver: webdriver.Chrome, review_element: WebElement, store_name: str
) -> Optional[Dict[str, str]]:
    """Extract a single review dictionary from a WebElement."""
    try:
        # Reviewer name
        try:
            reviewer = review_element.find_element(By.CSS_SELECTOR, "div.d4r55").text.strip()
        except NoSuchElementException:
            reviewer = ""

        # Rating
        rating = None
        try:
            rating_span = review_element.find_element(By.CSS_SELECTOR, "span.kvMYJc")
            rating = _parse_rating(rating_span.get_attribute("aria-label") or "")
        except NoSuchElementException:
            try:
                rating_span = review_element.find_element(By.CSS_SELECTOR, 'span[role="img"]')
                rating = _parse_rating(rating_span.get_attribute("aria-label") or "")
            except NoSuchElementException:
                pass

        # Date
        review_date = ""
        try:
            date_span = review_element.find_element(By.CSS_SELECTOR, "span.rsqaWe")
            review_date = date_span.text.strip()
        except NoSuchElementException:
            try:
                date_span = review_element.find_element(By.CSS_SELECTOR, 'span[class*="xRkPPb"]')
                review_date = date_span.text.strip()
            except NoSuchElementException:
                pass

        review_date = parse_relative_date(review_date)

        # Review Text (expand 'More' if necessary)
        review_text = ""
        try:
            more_button = review_element.find_element(By.CSS_SELECTOR, 'button.w8nwRe.kyuRq')
            try:
                driver.execute_script("arguments[0].click();", more_button)
            except ElementClickInterceptedException:
                more_button.click()
            time.sleep(0.2)
        except NoSuchElementException:
            pass

        try:
            review_text = review_element.find_element(By.CSS_SELECTOR, "span.wiI7pd").text.strip()
        except NoSuchElementException:
            pass  # Some reviews have ratings only

        review_id = review_element.get_attribute("data-review-id") or ""

        # Timezone-aware UTC timestamp
        return {
            "review_id": review_id,
            "store_name": store_name,
            "reviewer_name": reviewer,
            "rating": rating,
            "review_text": review_text,
            "review_date": review_date,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        }

    except StaleElementReferenceException:
        logger.warning("Stale element encountered; skipping review.")
        return None
    except WebDriverException as exc:
        logger.warning("Error extracting review: %s", exc)
        return None


# extract_reviews was removed as its functionality is now merged into scroll_and_extract_reviews


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def run_scraper() -> Dict[str, int]:
    """
    Main scraper entry point. Iterates over configured URLs, opens reviews,
    scrolls to load all items, upserts to MongoDB, and exports the results.
    """
    try:
        from database import upsert_review
    except ImportError as exc:
        logger.error("Cannot import upsert_review from database.py: %s", exc)
        return {}
    try:
        from export import export_all
    except ImportError as exc:
        logger.error("Cannot import export_all from export.py: %s", exc)
        return {}

    # Run statistics tracking
    stats = {
        "start_time": datetime.now(timezone.utc),
        "stores_processed": 0,
        "stores_failed": 0,
        "reviews_extracted": 0,
        "upsert_errors": 0,
    }

    driver = setup_driver()

    try:
        for url in STORES:
            current_store_name = "Unknown"
            try:
                if not open_store(driver, url):
                    stats["stores_failed"] += 1
                    continue
                current_store_name = get_store_name(driver)
                logger.info("Processing Store: %s", current_store_name)

                if not open_reviews(driver):
                    logger.warning("Skipping '%s' — reviews unavailable.", current_store_name)
                    stats["stores_failed"] += 1
                    continue

                # Give the reviews panel time to fully render
                time.sleep(5)

                # Save HTML and screenshot for debugging (now captures the active reviews panel)
                with open("page.html", "w", encoding="utf-8") as f:
                    f.write(driver.page_source)

                driver.save_screenshot("reviews_panel.png")
                logger.info("Saved page.html and reviews_panel.png for debugging the reviews panel")

                reviews = scroll_and_extract_reviews(driver, current_store_name)

                if not reviews:
                    logger.info("No reviews extracted for '%s'.", current_store_name)
                    stats["stores_processed"] += 1
                    continue

                for review in reviews:
                    try:
                        upsert_review(review)
                        stats["reviews_extracted"] += 1
                    except Exception as exc:
                        stats["upsert_errors"] += 1
                        logger.error(
                            "Upsert failed for review on '%s' (ID: %s): %s",
                            current_store_name, review.get("review_id", "N/A"), exc
                        )

                stats["stores_processed"] += 1
                logger.info("Finished processing '%s'.", current_store_name)

            except WebDriverException as exc:
                stats["stores_failed"] += 1
                logger.error("Driver error on store '%s' (%s): %s", current_store_name, url, exc)
            except Exception as exc:
                stats["stores_failed"] += 1
                logger.exception("Unexpected error on store '%s': %s", current_store_name, exc)

    finally:
        logger.info("Closing WebDriver.")
        driver.quit()

    stats["end_time"] = datetime.now(timezone.utc)
    duration = stats["end_time"] - stats["start_time"]

    logger.info("=== Scraping Summary ===")
    logger.info("Duration:              %s", duration)
    logger.info("Stores processed OK:   %d", stats["stores_processed"])
    logger.info("Stores failed:         %d", stats["stores_failed"])
    logger.info("Reviews extracted:     %d", stats["reviews_extracted"])
    logger.info("Upsert errors:         %d", stats["upsert_errors"])

    try:
        logger.info("Initiating data export...")
        export_all()
        logger.info("Export to JSON/CSV complete.")
    except Exception as exc:
        logger.error("export_all() failed: %s", exc)

    return {
        "stores_processed": stats["stores_processed"],
        "stores_failed": stats["stores_failed"],
        "reviews_extracted": stats["reviews_extracted"],
        "upsert_errors": stats["upsert_errors"]
    }


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    run_scraper()