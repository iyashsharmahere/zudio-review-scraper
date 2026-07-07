import json,pandas as pd
from database import get_reviews


def export_all():
    data=get_reviews()
    with open('data/reviews.json','w',encoding='utf-8') as f: json.dump(data,f,indent=2,ensure_ascii=False)
    pd.DataFrame(data).to_csv('data/reviews.csv',index=False)
