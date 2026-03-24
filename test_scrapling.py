from scrapling import StealthyFetcher
import time

def test():
    print("Testing Scrapling StealthyFetcher...")
    url = "https://example.com"
    print(f"Scraping {url}...")
    start = time.time()
    try:
        response = StealthyFetcher.fetch(url)
        print(f"Status: {response.status_code}")
        print(f"Content Length: {len(response.text)}")
        print(f"Duration: {time.time() - start:.2f}s")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    test()
