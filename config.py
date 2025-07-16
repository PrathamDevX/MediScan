SCRAPING_CONFIG = {
    'CONCURRENT_REQUESTS': 4,
    'REQUEST_TIMEOUT': 10,
    'RETRY_TIMES': 2,
    'DOWNLOAD_DELAY': 0.5,
    'RANDOMIZE_DOWNLOAD_DELAY': True,
    'USER_AGENTS': [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Firefox/89.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/605.1.15'
    ]
}

CACHE_CONFIG = {
    'ENABLED': True,
    'EXPIRE_AFTER': 3600,  # 1 hour
    'MAX_SIZE': 1000
}