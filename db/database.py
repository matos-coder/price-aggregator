import os
import time
import logging

import meilisearch
from dotenv import load_dotenv
from meilisearch.errors import MeilisearchApiError, MeilisearchCommunicationError

logger = logging.getLogger("ProductDatabase")

# Load environment variables
load_dotenv()

# Common shopper vocabulary — lets "mac book" find "MacBook" listings etc.
SYNONYMS = {
    "macbook": ["mac book"],
    "mac book": ["macbook"],
    "iphone": ["i phone"],
    "i phone": ["iphone"],
    "laptop": ["notebook"],
    "notebook": ["laptop"],
    "tv": ["television"],
    "television": ["tv"],
    "ps5": ["playstation 5"],
    "playstation 5": ["ps5"],
    "ps4": ["playstation 4"],
    "playstation 4": ["ps4"],
}


class ProductDatabase:
    def __init__(self):
        host = os.getenv("MEILI_HOST")
        api_key = os.getenv("MEILI_MASTER_KEY")

        self.client = meilisearch.Client(host, api_key)
        self.index_name = "products"

        # Meilisearch may still be booting inside the container — retry.
        max_retries = 10
        for attempt in range(1, max_retries + 1):
            try:
                self.client.health()
                break
            except MeilisearchCommunicationError:
                logger.warning(f"Meilisearch not ready at {host}... retrying ({attempt}/{max_retries})")
                time.sleep(3)
        else:
            logger.error(f"Could not connect to Meilisearch at {host} after {max_retries} attempts.")
            raise SystemExit(1)

        try:
            self.client.get_index(self.index_name)
        except MeilisearchApiError:
            logger.info("Creating 'products' index with primary key...")
            task = self.client.create_index(self.index_name, {"primaryKey": "id"})
            self.client.wait_for_task(task.task_uid)

        self.index = self.client.index(self.index_name)

    def setup_index(self):
        """
        Configures the search engine rules. This is critical for handling
        complex user queries (like price limits and location filtering).
        """
        logger.info("Configuring Meilisearch index...")

        # 1. Searchable Attributes: what the engine looks at for a text query.
        self.index.update_searchable_attributes([
            'product_name',
            'original_text'
        ])

        # 2. Filterable Attributes: strict filtering (e.g., price <= 80000).
        self.index.update_filterable_attributes([
            'price',
            'location',
            'channel_username'
        ])

        # 3. Sortable Attributes: cheapest price or newest post first.
        self.index.update_sortable_attributes([
            'price',
            'timestamp'
        ])

        # 4. Synonyms: common spelling variants shoppers actually type.
        self.index.update_synonyms(SYNONYMS)

        logger.info("Index configuration complete.")

    def document_exists(self, doc_id: str) -> bool:
        """True if a listing with this id is already indexed (dedupe check)."""
        try:
            self.index.get_document(doc_id)
            return True
        except MeilisearchApiError:
            return False

    def add_product(self, product_data: dict, wait: bool = False):
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
        try:
            task = self.index.add_documents([product_data])
            if wait:
                self.client.wait_for_task(task.task_uid)
            logger.info(f"Inserted: {product_data['id']}")
            return task
        except Exception as e:
            logger.error(f"Insert error for {product_data.get('id')}: {e}")

    def search_products(self, query: str, max_price: int = None, location: str = None):
        """
        Executes a lightning-fast, typo-tolerant search.
        """
        search_params = {
            'limit': 10,  # Only return the top 10 results to the Telegram user
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
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    db = ProductDatabase()
    db.setup_index()
