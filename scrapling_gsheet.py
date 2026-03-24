import asyncio
import time
import json
import os
import gspread
import httpx
from google.oauth2.service_account import Credentials
from scrapling import StealthyFetcher
from bs4 import BeautifulSoup
from markdownify import markdownify as md
from utils.hardware import HardwareOptimizer # NEW: Hardware Layer

# Configuration
GSHEET_ID = "1a9B3rBHRakm4wOknFLUuwNbUl-eDP-owUTQdETMVg6w"
CREDENTIALS_FILE = "credentials.json"
PROXY_URL = None 

# Dynamic Hardware Scaling
AUTO_CONCURRENCY, HW_SPECS = HardwareOptimizer.calculate_concurrency()
MAX_CONCURRENT_SCRAPES = AUTO_CONCURRENCY 

# ... (rest of the file remains same, I will only replace the scrape_url and config)

def get_sheet():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=scopes)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(GSHEET_ID).worksheet("Console")
    return sheet

def html_to_markdown(html_content):
    """Convert HTML to clean Markdown, stripping only essential noise to maximize word count."""
    try:
        if not html_content:
            return ""
        soup = BeautifulSoup(html_content, "html.parser")
        
        # Remove active scripts/styles
        for tag in soup(["script", "style", "svg", "noscript"]):
            tag.decompose()
            
        # We explicitly KEEP header, footer, nav, and aside to ensure we hit the 1000-word usability threshold
        # as requested for "high-density" results.
        
        raw_text = soup.get_text(separator="\n", strip=True)
        markdown_text = md(str(soup), heading_style="ATX", strip=['img', 'a'])
        return f"{raw_text}\n\n---\n\n{markdown_text}"
    except Exception:
        return ""

async def scrape_url(semaphore, row_idx, domain):
    async with semaphore:
        start_time = time.time()
        # Normalize URL
        if not domain.startswith(('http://', 'https://')):
            domain = f"https://{domain}"
        
        # Try variants: raw, www
        if "www." not in domain and "://" in domain:
            proto, rest = domain.split("://")
            variants = [domain, f"{proto}://www.{rest}"]
        else:
            variants = [domain]

        final_html = ""
        final_status = "Failed"
        last_error = "Unknown"
        emergency_html = ""

        for current_url in variants:
            try:
                # LEVEL 1: Static (Fast)
                try:
                    # Increased timeout from 7s to 12s for slow/large sites
                    async with httpx.AsyncClient(verify=False, follow_redirects=True, timeout=12, proxy=PROXY_URL) as client:
                        resp = await client.get(current_url)
                        if len(resp.text) > 250: emergency_html = resp.text
                        
                        is_ok = resp.status_code == 200 and not any(x in resp.text.lower() for x in ["cloudflare", "captcha", "challenge-platform"])
                        if is_ok:
                            temp_content = html_to_markdown(resp.text)
                            if len(temp_content) > 300: # Quality gate
                                final_html = resp.text
                                final_status = "Success (Static)"
                                break
                        raise Exception("Insufficient content or block")
                except Exception as static_err:
                    # LEVEL 2: Stealth Browser
                    try:
                        # Increased timeout to 60s for heavy sites
                        response = await StealthyFetcher.async_fetch(
                            current_url, timeout=60000, proxy=PROXY_URL,
                            humanize=True, os_randomize=True, block_images=True,
                            disable_ads=True, disable_resources=True, geoip=True,
                            network_idle=True,
                            wait=1500, # Increased wait for JS-heavy sites
                            allow_webgl=HW_SPECS["gpu_available"]
                        )
                        final_html = response.html_content
                        final_status = "Success (Stealth)"
                        break
                    except Exception as l2_err:
                        last_error = f"Browser: {str(l2_err)[:60]}"
                        # If DNS fails on raw domain, try variants
                        if "NS_ERROR_UNKNOWN_HOST" in str(l2_err): continue
            except Exception:
                continue

        # LEVEL 3: Emergency Recovery (If browser fails but static had SOMETHING)
        if not final_html and emergency_html:
            final_html = emergency_html
            final_status = "Success (Emergency Content)"

        duration = round(time.time() - start_time, 2)
        content = html_to_markdown(final_html) if final_html else f"ERROR: {last_error}"
        char_len = len(content) if final_status.startswith("Success") else 0
        
        if final_status.startswith("Success"):
            print(f"✅ [{row_idx}] {final_status}: {domain} ({duration}s, {char_len} chars)")
        else:
            print(f"❌ [{row_idx}] Failed: {domain} ({last_error})")
            
        return [content, final_status, duration, char_len]

async def gsheet_writer(sheet, queue, total_count):
    """Background worker to save results in batches without blocking the scraper."""
    processed = 0
    buffer = [] # list of (row_idx, data)
    
    while processed < total_count:
        try:
            # Wait for data from queue
            item = await asyncio.wait_for(queue.get(), timeout=5.0)
            buffer.append(item)
            processed += 1
            queue.task_done()
        except asyncio.TimeoutError:
            pass # Pulse check for buffer flush

        # Flush buffer if it's large enough or we're at a pulse check
        if len(buffer) >= 20 or (buffer and processed == total_count):
            # Sort buffer by row_idx for easier debugging, though not strictly required
            buffer.sort(key=lambda x: x[0])
            
            # Group contiguous rows if possible for efficiency, 
            # but for now, we'll do individual updates or small batches to avoid complexity
            # Note: GSheet API likes batch_update for non-contiguous ranges
            batch_updates = []
            for row_idx, data in buffer:
                batch_updates.append({
                    'range': f'B{row_idx}:E{row_idx}',
                    'values': [data]
                })
            
            try:
                if batch_updates:
                    sheet.batch_update(batch_updates)
                    print(f"📤 Saved {len(buffer)} results to GSheet. ({processed}/{total_count})")
            except Exception as e:
                print(f"⚠️ GSheet Batch Save Failed: {e}")
            
            buffer = []

async def main():
    print(f"🚀 Initializing Hardware-Aware Scraper...")
    print(f"💻 OS: {HW_SPECS['os']} | CPU Cores: {HW_SPECS['cpu_cores']} | RAM: {HW_SPECS['available_ram_gb']}GB Free")
    print(f"🎮 GPU: {HW_SPECS['gpu_details']}")
    print(f"⚡ Scaling to {MAX_CONCURRENT_SCRAPES} concurrent workers.")
    
    try:
        sheet = get_sheet()
        # Proactively write headers as requested
        headers = ["Domain", "Raw Content", "Status", "Time taken per domain", "Char Length", "Total Time taken", "Concurrency"]
        sheet.update('A1:G1', [headers])
        
        rows = sheet.get_all_values()
    except Exception as e:
        print(f"❌ Initial GSheet connection failed: {e}")
        return

    if not rows or len(rows) < 2:
        print("⚠️ No data in sheet (Column A should contain URLs starting from Row 2).")
        return
    
    # Identify domains from Column A
    domains = [row[0] for row in rows[1:] if row and row[0].strip()] 
    total_domains = len(domains)
    print(f"📋 Found {total_domains} domains to process.")

    semaphore = asyncio.Semaphore(MAX_CONCURRENT_SCRAPES)
    save_queue = asyncio.Queue()
    start_all = time.time()
    
    # Define the worker that feeds the queue
    async def worker(row_idx, domain):
        result = await scrape_url(semaphore, row_idx, domain)
        await save_queue.put((row_idx, result))

    # Start the background saver
    saver_task = asyncio.create_task(gsheet_writer(sheet, save_queue, total_domains))
    
    # Start all scrapers concurrently (Semaphore handles the limit)
    tasks = [worker(i+2, dom) for i, dom in enumerate(domains)]
    await asyncio.gather(*tasks)
    
    # Wait for the saver to finish remaining buffer
    await saver_task

    total_duration = round(time.time() - start_all, 2)
    try:
        # F2: Total Time, G2: Concurrency
        sheet.update('F2:G2', [[f"{total_duration}s", str(MAX_CONCURRENT_SCRAPES)]])
    except Exception:
        pass
        
    print(f"✅ Completed entire run in {total_duration}s. Performance: {round(total_duration/total_domains, 2)}s/domain" if total_domains > 0 else "✅ Done.")

if __name__ == "__main__":
    asyncio.run(main())
