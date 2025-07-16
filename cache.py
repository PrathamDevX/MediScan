from functools import lru_cache
from datetime import datetime, timedelta

class SearchCache:
    def __init__(self):
        self.cache = {}
        self.timestamps = {}
    
    def get(self, key):
        if key in self.cache:
            if datetime.now() - self.timestamps[key] < timedelta(hours=1):
                return self.cache[key]
            else:
                del self.cache[key]
                del self.timestamps[key]
        return None
    
    def set(self, key, value):
        self.cache[key] = value
        self.timestamps[key] = datetime.now()
        
        # Cleanup old entries
        current_time = datetime.now()
        expired_keys = [k for k, t in self.timestamps.items() 
                       if current_time - t > timedelta(hours=1)]
        
        for k in expired_keys:
            del self.cache[k]
            del self.timestamps[k]

search_cache = SearchCache()