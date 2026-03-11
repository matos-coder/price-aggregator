import os
import meilisearch
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class ProductDatabase:
    def __init__(self):
        # Initialize Meilisearch client (default local port is 7700)
        # In production, MEILI_HOST and MEILI_MASTER_KEY will be in your .env
        host = os.getenv("MEILI_HOST")
        api_key = os.getenv("MEILI_MASTER_KEY")
        
        self.client = meilisearch.Client(host, api_key)
        self.index_name = "products"
        self.index = self.client.index(self.index_name)
        
    def setup_index(self):
        """
        Configures the search engine rules. This is critical for handling 
        complex user queries (like price limits and location filtering).
        """
        print("Configuring Meilisearch index...")
        
        # 1. Searchable Attributes: What fields should the engine look at when a user types a query?
        self.index.update_searchable_attributes([
            'product_name',
            'original_text'
        ])
        
        # 2. Filterable Attributes: What fields will we use for strict filtering (e.g., price < 80000)?
        self.index.update_filterable_attributes([
            'price',
            'location',
            'channel_username'
        ])
        
        # 3. Sortable Attributes: Allow sorting by cheapest price or newest post.
        self.index.update_sortable_attributes([
            'price',
            'timestamp'
        ])
        
        print("Index configuration complete.")

    def add_product(self, product_data: dict):
        """
        Inserts a newly scraped and extracted product into the search engine.
        Expected dict format:
        {
            "id": "nevacomputer_1045", # Unique ID: channel + message_id
            "channel_username": "nevacomputer",
            "message_id": 1045,
            "product_name": "Macbook Pro M2",
            "price": 120000,
            "location": "Bole",
            "original_text": "አዲስ ማክቡክ ፕሮ...",
            "timestamp": 1700000000
        }
        """
        task = self.index.add_documents([product_data])
        return task

    def search_products(self, query: str, max_price: int = None, location: str = None):
        """
        Executes a lightning-fast, typo-tolerant search.
        """
        search_params = {
            'limit': 10, # Only return the top 10 results to the Telegram user
        }
        
        # Build strict filters if the user requested them
        filters = []
        if max_price:
            filters.append(f"price <= {max_price}")
        if location:
            filters.append(f"location = '{location}'")
            
        if filters:
            search_params['filter'] = " AND ".join(filters)

        return self.index.search(query, search_params)

# Run this file directly to initialize your database structure
if __name__ == "__main__":
    db = ProductDatabase()
    db.setup_index()