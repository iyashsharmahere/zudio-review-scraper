from pymongo import MongoClient
from config import MONGO_URI, DB_NAME, COLLECTION

client = MongoClient(MONGO_URI)

db = client[DB_NAME]
collection = db[COLLECTION]


def upsert_review(review):
    collection.update_one(
        {
            "store_name": review["store_name"],
            "reviewer_name": review["reviewer_name"],
            "review_text": review["review_text"]   # <-- changed
        },
        {
            "$set": review
        },
        upsert=True
    )  


def get_reviews():
    return list(collection.find({}, {"_id": 0}))