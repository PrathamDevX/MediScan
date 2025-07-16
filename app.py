from flask import Flask, render_template, request, jsonify
from models import db, FeaturedProduct
from omnidimension import Client
from dotenv import load_dotenv
import os
import chromedriver_autoinstaller
chromedriver_autoinstaller.install()
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import requests
from bs4 import BeautifulSoup
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import aiohttp
import asyncio
import httpx
from geopy.distance import geodesic
import json

# Load environment variables
load_dotenv()

# Get API key
GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY')

# Initialize OmniDimension client
client = Client(os.getenv('OMNIDIMENSION_API_KEY'))

app = Flask(__name__)

# Database configuration
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'medifind.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize database
db.init_app(app)

# Create tables
with app.app_context():
    db.create_all()

# Function to seed initial featured products
def seed_featured_products():
    with app.app_context():
        if FeaturedProduct.query.count() == 0:
            products = [
                {
                    'name': 'Dolo 650 Tablet',
                    'price': 30.25,
                    'pharmacy': 'Apollo',
                    'delivery': 40,
                    'link': 'https://www.apollopharmacy.in/otc/dolo-650mg-tablet-15s',
                    'image_url': 'https://newassets.apollo247.com/pub/media/catalog/product/d/o/dol0119_1.jpg'
                },
                {
                    'name': 'Blood Glucose Monitor',
                    'price': 999.00,
                    'pharmacy': 'PharmEasy',
                    'delivery': 50,
                    'link': 'https://pharmeasy.in/health-care/products/accu-chek-active-glucose-monitor-with-10-strips-9051',
                    'image_url': 'https://cdn01.pharmeasy.in/dam/products_otc/I05582/accu-chek-active-glucose-monitor-with-10-strips-2-1654168589.jpg'
                }
            ]
            
            for product in products:
                featured = FeaturedProduct(**product)
                db.session.add(featured)
            
            db.session.commit()
            print("✅ Featured products seeded successfully")

# Update PHARMACIES dictionary first
PHARMACIES = {
    "Apollo": "https://www.apollopharmacy.in/search-medicines/{}",
    "1mg": "https://www.1mg.com/search/all?name={}",
    "PharmEasy": "https://pharmeasy.in/search/all?name={}",
    "TrueMeds": "https://www.truemeds.in/search/{}",
}

# Replace Netmeds scraper with Apollo scraper
def scrape_apollo_selenium(medicine):
    print("[Apollo] Scraping...")
    options = Options() 
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--window-size=1920,1080')
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/115.0.0.0 Safari/537.36")
    options.add_experimental_option('excludeSwitches', ['enable-automation'])
    options.add_experimental_option('useAutomationExtension', False)

    driver = webdriver.Chrome(options=options)
    results = []

    try:
        # Direct search without homepage visit
        search_url = f"https://www.apollopharmacy.in/search-medicines/{medicine.replace(' ', '-')}"
        driver.get(search_url)
        time.sleep(5)

        # Wait for product cards with specific selector
        wait = WebDriverWait(driver, 15)
        try:
            cards = wait.until(EC.presence_of_all_elements_located((
                By.CSS_SELECTOR, "div[class*='ProductCard_productCardGrid']"
            )))
            print(f"[Apollo] Found {len(cards)} products")
        except Exception as e:
            print(f"[Apollo] Failed to find products: {e}")
            return results

        for card in cards[:5]:
            try:
                # Get name and link using specific selectors from your HTML
                name_elem = card.find_element(By.CSS_SELECTOR, "div.zb h2.jR")
                name = name_elem.text.strip()
                
                link_elem = card.find_element(By.CSS_SELECTOR, "a[href*='/otc/']")
                link = link_elem.get_attribute("href")

                # Get price using specific selector
                try:
                    price_elem = card.find_element(By.CSS_SELECTOR, "span.zL_")
                    price_text = price_elem.text.strip()
                    if not price_text:
                        price_elem = card.find_element(By.CSS_SELECTOR, "p.oR.hR")
                        price_text = price_elem.text.strip()
                except:
                    continue

                # Clean price text
                price = float(re.sub(r'[^\d.]', '', price_text))

                if name and price:
                    delivery = 40  # Apollo's standard delivery charge
                    results.append({
                        "name": name,
                        "price": price,
                        "pharmacy": "Apollo",
                        "delivery": delivery,
                        "final_price": price + delivery,
                        "link": link
                    })
                    print(f"[Apollo] Found: {name} at ₹{price}")

            except Exception as e:
                print(f"[Apollo] Card error: {str(e)}")
                continue

    except Exception as e:
        print(f"[Apollo] Error: {str(e)}")
    finally:
        driver.quit()

    return results

def clean_price(price_str):
    return float(price_str.replace("₹", "").replace(",", "").strip())

# 🟢 1mg Scraper (Selenium)
def scrape_1mg_selenium(medicine):
    print("[1mg] Scraping...")
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--window-size=1920,1080')
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
    
    driver = webdriver.Chrome(options=options)
    results = []
    
    try:
        # First load the main page
        driver.get("https://www.1mg.com")
        time.sleep(2)
        
        # Then perform the search
        search_url = f"https://www.1mg.com/search/all?name={medicine.replace(' ', '+')}"
        driver.get(search_url)
        time.sleep(3)
        
        # Scroll down slightly to trigger lazy loading
        driver.execute_script("window.scrollBy(0, 300);")
        time.sleep(2)
        
        # Wait for any of these selectors to be present
        selectors = [
            "div.style_horizontal-card___1Zwmt",
            "div[class*='horizontal-card']",
            "div.style__horizontal-card___1Zwmt"
        ]
        
        cards = None
        wait = WebDriverWait(driver, 15)
        for selector in selectors:
            try:
                cards = wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, selector)))
                if cards:
                    print(f"[1mg] Found cards with selector: {selector}")
                    break
            except:
                continue
        
        if not cards:
            print("[1mg] No product cards found")
            return results
            
        for card in cards[:5]:
            try:
                # Get name and link
                link_elem = card.find_element(By.TAG_NAME, "a")
                name = link_elem.get_attribute("title") or link_elem.text.strip()
                link = link_elem.get_attribute("href")
                
                # Try multiple price selectors
                price = "0"
                price_selectors = [
                    "span[class*='price']",
                    "span[class*='mrp']",
                    "div[class*='price']"
                ]
                
                for price_selector in price_selectors:
                    try:
                        price_elem = card.find_element(By.CSS_SELECTOR, price_selector)
                        price_text = price_elem.text.strip()
                        # Extract numbers from price text
                        price_match = re.search(r'[\d,]+', price_text)
                        if price_match:
                            price = price_match.group()
                            break
                    except:
                        continue

                delivery = 25
                results.append({
                    "name": name,
                    "price": clean_price(price),
                    "pharmacy": "1mg",
                    "delivery": delivery,
                    "final_price": clean_price(price) + delivery,
                    "link": link
                })
                print(f"[1mg] Found product: {name} at ₹{price}")
            except Exception as e:
                print(f"[1mg] Card error: {e}")
                
    except Exception as e:
        print(f"[1mg] Error: {e}")
    finally:
        driver.quit()
        
    return results

# 🔵 PharmEasy Scraper (Selenium)
def scrape_pharmeasy_selenium(medicine):
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument("user-agent=Mozilla/5.0")

    driver = webdriver.Chrome(options=options)
    results = []

    try:
        url = PHARMACIES["PharmEasy"].format(medicine.replace(" ", "%20"))
        driver.get(url)

        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, 'div.ProductCard_medicineUnitContainer__m2_zO'))
        )
        time.sleep(2)

        cards = driver.find_elements(By.CSS_SELECTOR, "div.ProductCard_medicineUnitContainer__m2_zO")
        for card in cards[:5]:
            try:
                name = card.find_element(By.CSS_SELECTOR, "a.ProductCard_defaultWrapper__h4yf3").text.strip()
                # Corrected selector below
                try:
                    price_text = card.find_element(By.CSS_SELECTOR, "div.ProductCard_mrp__ibLhX").text.strip()
                except:
                    price_text = card.find_element(By.CSS_SELECTOR, "span").text.strip()  # fallback if class changes
                price = float(re.sub(r'[^\d.]', '', price_text))
                link = card.find_element(By.CSS_SELECTOR, "a.ProductCard_defaultWrapper__h4yf3").get_attribute("href")
                results.append({
                    "name": name,
                    "price": price,
                    "pharmacy": "PharmEasy",
                    "link": link
                })
            except Exception as e:
                print("⚠️ PharmEasy card error:", e)
    except Exception as e:
        print("❌ PharmEasy selenium error:", e)
    finally:
        driver.quit()

    return results

# TrueMeds Scraper (Selenium)
def scrape_truemeds_selenium(medicine):
    print("[TrueMeds] Scraping...")
    options = Options()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--window-size=1920,1080')
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/115.0.0.0 Safari/537.36")
    
    driver = webdriver.Chrome(options=options)
    results = []

    try:
        search_url = PHARMACIES["TrueMeds"].format(medicine.replace(" ", "+"))
        driver.get(search_url)
        time.sleep(5)

        # Use the exact class from HTML
        wait = WebDriverWait(driver, 15)
        try:
            cards = wait.until(EC.presence_of_all_elements_located((
                By.CSS_SELECTOR, "div.sc-a39eeb4f-1.zdA-dE"
            )))
            print(f"[TrueMeds] Found {len(cards)} products")
        except Exception as e:
            print(f"[TrueMeds] Failed to find products: {e}")
            return results

        for card in cards[:5]:
            try:
                data = {}

                # Get name - exact class from HTML
                name_elem = card.find_element(By.CSS_SELECTOR, "div.sc-a39eeb4f-12.daYLth")
                data['name'] = name_elem.text.strip()

                # Get manufacturer - exact class from HTML
                mfg_elem = card.find_element(By.CSS_SELECTOR, "span.sc-a39eeb4f-14.faASZT")
                data['manufacturer'] = mfg_elem.text.strip()

                # Get actual price - exact class from HTML
                try:
                    actual_price_elem = card.find_element(By.CSS_SELECTOR, "span.sc-a39eeb4f-17.iwZSqt")
                    price_text = actual_price_elem.text.replace('₹', '').strip()
                    data['price'] = float(price_text)
                except:
                    # Fallback to MRP if discounted price not found
                    mrp_elem = card.find_element(By.CSS_SELECTOR, "span.sc-a39eeb4f-20.eVOcGs")
                    price_text = mrp_elem.text.replace('MRP ₹', '').replace('del', '').strip()
                    data['price'] = float(re.sub(r'[^\d.]', '', price_text))

                # Get product slug from the image URL
                img_elem = card.find_element(By.CSS_SELECTOR, "img[alt*='Dolo']")
                img_src = img_elem.get_attribute("src")
                
                # Extract product ID from image URL (e.g., TM-TACR1-011691)
                product_id = re.search(r'TM-[A-Z0-9-]+', img_src).group(0).lower()
                
                # Format product name for URL (e.g., dolo-650-mg-tablet-15)
                product_name = data['name'].lower().replace(' ', '-')
                
                # Construct the correct OTC URL
                data['link'] = f"https://www.truemeds.in/otc/{product_name}-{product_id}"
            

                # Get discount percentage if available
                try:
                    discount_elem = card.find_element(By.CSS_SELECTOR, "span.sc-a39eeb4f-21.jQaxpC")
                    discount = discount_elem.text.strip()
                    print(f"[TrueMeds] Discount: {discount}")
                except:
                    pass

                if data['name'] and data['price']:
                    delivery = 35
                    results.append({
                        "name": f"{data['name']} by {data['manufacturer']}".strip(),
                        "price": data['price'],
                        "pharmacy": "TrueMeds",
                        "delivery": delivery,
                        "final_price": data['price'] + delivery,
                        "link": data['link']  # This will now be the product page URL
                    })
                    print(f"[TrueMeds] Found: {data['name']} at ₹{data['price']}")

            except Exception as e:
                print(f"[TrueMeds] Card error: {str(e)}")
                print("[TrueMeds] Card HTML:", card.get_attribute('outerHTML'))
                continue

    except Exception as e:
        print(f"[TrueMeds] Error: {str(e)}")
    finally:
        driver.quit()

    return results

# Add this async Apollo scraper after your existing scrapers
async def scrape_apollo_async(medicine):
    results = []
    try:
        url = f"https://www.apollopharmacy.in/search-medicines/{medicine.replace(' ', '-')}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/115.0.0.0 Safari/537.36'
        }
        
        html = await fetch_pharmacy_data(url, headers)
        soup = BeautifulSoup(html, 'html.parser')
        
        cards = soup.select("div[class*='ProductCard_productCardGrid']")[:5]
        
        for card in cards:
            try:
                name = card.select_one("div.zb h2.jR").text.strip()
                price_elem = card.select_one("span.zL_") or card.select_one("p.oR.hR")
                
                if name and price_elem:
                    price = float(re.sub(r'[^\d.]', '', price_elem.text))
                    link = "https://www.apollopharmacy.in" + card.select_one("a[href*='/otc/']")['href']
                    
                    results.append({
                        "name": name,
                        "price": price,
                        "pharmacy": "Apollo",
                        "delivery": 40,
                        "final_price": price + 40,
                        "link": link
                    })
            except Exception as e:
                print(f"[Apollo Async] Card error: {e}")
                continue
                
    except Exception as e:
        print(f"[Apollo Async] Error: {e}")
    
    return results

# Update the parallel_scrape_async function to include TrueMeds
async def parallel_scrape_async(medicine):
    tasks = [
        scrape_pharmeasy_async(medicine),
        scrape_apollo_async(medicine),
        # Commenting out 1mg async since it's not implemented yet
        # scrape_1mg_async(medicine)  
    ]
    
    results = []
    try:
        completed_tasks = await asyncio.gather(*tasks)
        for task_result in completed_tasks:
            results.extend(task_result)
    except Exception as e:
        print(f"Parallel scrape error: {e}")
    
    # Add selenium-based scrapers results
    selenium_results = []
    with ThreadPoolExecutor(max_workers=3) as executor:
        selenium_tasks = [
            executor.submit(scrape_1mg_selenium, medicine),
            executor.submit(scrape_truemeds_selenium, medicine)
        ]
        for future in as_completed(selenium_tasks):
            try:
                selenium_results.extend(future.result())
            except Exception as e:
                print(f"Selenium scraper error: {e}")
    
    results.extend(selenium_results)
    return results

# Create connection pools
session = httpx.Client(timeout=10.0, limits=httpx.Limits(max_keepalive_connections=5))
executor = ThreadPoolExecutor(max_workers=4)

async def fetch_pharmacy_data(url, headers):
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            return await response.text()

async def scrape_pharmeasy_async(medicine):
    results = []
    try:
        url = f"https://pharmeasy.in/search/all?name={medicine}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as response:
                html = await response.text()
                
        soup = BeautifulSoup(html, 'html.parser')
        products = soup.find_all('div', {'class': 'ProductCard_productCard__ergV2'})[:5]
        
        for product in products:
            try:
                name = product.find('h1', {'class': 'ProductCard_medicineName__8Ydfq'})
                price = product.find('div', {'class': 'ProductCard_gcdDiscountContainer__CCi51'})
                
                if name and price:
                    price_text = price.text.replace('₹', '').strip()
                    price_value = float(re.sub(r'[^\d.]', '', price_text))
                    
                    results.append({
                        'name': name.text.strip(),
                        'price': price_value,
                        'pharmacy': 'PharmEasy',
                        'delivery': 50.0,
                        'final_price': price_value + 50.0,
                        'link': f"https://pharmeasy.in{product.find('a')['href']}"
                    })
                    
            except Exception as e:
                print(f"[PharmEasy Async] Product error: {e}")
                continue
                
    except Exception as e:
        print(f"[PharmEasy Async] Error: {e}")
    
    return results

# Similar optimizations for other pharmacy scrapers
# ...existing code...

async def parallel_scrape_async(medicine):
    tasks = [
        scrape_pharmeasy_async(medicine),
        scrape_apollo_async(medicine),
        # Commenting out 1mg async since it's not implemented yet
        # scrape_1mg_async(medicine)  
    ]
    
    results = []
    async with asyncio.TaskGroup() as tg:
        for coro in tasks:
            task = tg.create_task(coro)
            results.extend(await task)
    
    return results

def parallel_scrape(medicine):
    async def run_async():
        tasks = [
            scrape_pharmeasy_async(medicine),
            scrape_apollo_async(medicine)
        ]
        results = []
        
        # Run async tasks
        async_results = await asyncio.gather(*tasks, return_exceptions=True)
        for result in async_results:
            if isinstance(result, list):  # Only add successful results
                results.extend(result)
        
        # Run selenium tasks in thread pool
        with ThreadPoolExecutor(max_workers=3) as executor:
            selenium_tasks = [
                executor.submit(scrape_1mg_selenium, medicine),
                executor.submit(scrape_truemeds_selenium, medicine)
            ]
            for future in as_completed(selenium_tasks):
                try:
                    results.extend(future.result())
                except Exception as e:
                    print(f"Selenium scraper error: {e}")
        
        return results

    # Create new event loop for async operation
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        results = loop.run_until_complete(run_async())
    finally:
        loop.close()
    
    return results

# 🔷 Flask App Route
@app.route('/', methods=['GET', 'POST'])
def index():
    results = []
    featured_products = []
    search_attempted = False  # Add this flag
    
    if request.method == 'POST':
        medicine = request.form.get('medicine')
        quantity = request.form.get('quantity')
        search_attempted = True  # Set flag when search is attempted
        
        print(f"\n🔍 Searching for: {medicine}, Quantity: {quantity}\n")
        results = parallel_scrape(medicine)
        results.sort(key=lambda x: x['price'])
        
        featured_products = FeaturedProduct.query.order_by(
            FeaturedProduct.created_at.desc()
        ).limit(4).all()
        
        return render_template('index.html', 
                             results=results, 
                             search_complete=True,
                             search_attempted=search_attempted,  # Pass flag to template
                             no_results=len(results) == 0,
                             medicine_name=medicine,
                             featured_products=featured_products,
                             google_maps_api_key=GOOGLE_MAPS_API_KEY)  # Pass API key to template
    
    # Get featured products for homepage
    featured_products = FeaturedProduct.query.order_by(
        FeaturedProduct.created_at.desc()
    ).limit(4).all()
    
    google_maps_api_key = os.getenv('GOOGLE_MAPS_API_KEY')
    return render_template('index.html', 
                         results=results,
                         featured_products=featured_products,
                         search_attempted=search_attempted,  # Pass flag to template
                         google_maps_api_key=google_maps_api_key)  # Pass API key to template

# Call seed function when app starts
if __name__ == '__main__':
    seed_featured_products()
    app.run(debug=True)

# Create MediFind agent
def create_medifind_agent():
    try:
        response = client.agent.create(
            name="MedScan",  # Changed from MediFind to MedScan
            welcome_message="Hello, this is MedScan, your intelligent medicine search assistant. How can I assist you with your medication needs today?",  # Updated welcome message
            context_breakdown=[
                {"title": "Greeting and Intent Capture", 
                 "body": "Start by welcoming the user and encouraging them to describe their medicine query.",
                 "is_enabled": True},
                {"title": "Identify Medicine Composition", 
                 "body": "Once the user mentions a medicine, determine its chemical composition by accessing the comprehensive medicine database.",
                 "is_enabled": True},
                {"title": "Suggest Alternatives",
                 "body": "Using the chemical composition, compile a list of alternative medicines with the same composition.",
                 "is_enabled": True},
                {"title": "Display Real-Time Pricing",
                 "body": "Retrieve real-time pricing from trusted sources.",
                 "is_enabled": True}
            ],
            model={
                "model": "gpt-4",
                "temperature": 0.7
            }
        )
        return response['json'].get('id')
    except Exception as e:
        print(f"Failed to create agent: {e}")
        return None

# Initialize agent
agent_id = create_medifind_agent()

# Update the chat endpoint
@app.route('/chat', methods=['POST'])
def chat():
    if not agent_id:
        return jsonify({"error": "Chatbot not initialized"}), 500
        
    try:
        message = request.json.get('message')
        response = client.agent.chat(
            agent_id=agent_id,
            message=message
        )
        
        # Extract medicine info if available
        extracted = response.get('extracted_variables', {})
        medicine_name = extracted.get('medicine_name')
        
        # Get search results if medicine is mentioned
        results = []
        search_suggestion = None
        if medicine_name:
            results = parallel_scrape(medicine_name)
            results.sort(key=lambda x: x['price'])
            
            # Add search suggestion
            search_suggestion = {
                'medicine': medicine_name,
                'action': 'search',
                'message': f'Would you like to compare prices for {medicine_name}?'
            }
        print(f"[Chatbot] Extracted medicine: {medicine_name}, Alternatives: {extracted.get('alternative_medicines', [])}")
        return jsonify({
            "message": response.get('message'),
            "results": results,
            "alternatives": extracted.get('alternative_medicines', []),
            "search_suggestion": search_suggestion
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

import requests
from geopy.distance import geodesic
from flask import jsonify
import json
import os

def fetch_pmbjk_stores():
    """Fetch Jan Aushadhi Kendras from official API"""
    try:
        # Jan Aushadhi API endpoint
        url = "https://janaushadhi.gov.in/services/pmbi/store_list.php"
        
        response = requests.get(url)
        if response.status_code == 200:
            stores = response.json()
            # Process and clean store data
            processed_stores = []
            for store in stores:
                try:
                    processed_stores.append({
                        'name': store.get('storeName', '').strip(),
                        'address': f"{store.get('address', '')}, {store.get('city', '')}, {store.get('state', '')}",
                        'lat': float(store.get('latitude', 0)),
                        'lng': float(store.get('longitude', 0)),
                        'phone': store.get('mobileNo', ''),
                        'state': store.get('state', ''),
                        'city': store.get('city', '')
                    })
                except (ValueError, TypeError):
                    continue
            
            # Cache the results
            with open('store_cache.json', 'w') as f:
                json.dump(processed_stores, f)
                
            return processed_stores
    except Exception as e:
        print(f"Error fetching stores: {e}")
        # Try to load from cache if API fails
        if os.path.exists('store_cache.json'):
            with open('store_cache.json', 'r') as f:
                return json.load(f)
    return []

@app.route('/nearby-stores', methods=['POST'])
def find_nearby_stores():
    try:
        data = request.json
        user_lat = float(data.get('latitude'))
        user_lng = float(data.get('longitude'))
        user_location = (user_lat, user_lng)
        
        # Get stores from API or cache
        all_stores = fetch_pmbjk_stores()
        
        # Find stores within 5km radius
        nearby_stores = []
        for store in all_stores:
            if store['lat'] and store['lng']:  # Validate coordinates
                store_location = (store['lat'], store['lng'])
                distance = geodesic(user_location, store_location).kilometers
                
                if distance <= 5:  # 5km radius
                    store_data = store.copy()
                    store_data['distance'] = round(distance, 2)
                    nearby_stores.append(store_data)
        
        # Sort by distance
        nearby_stores.sort(key=lambda x: x['distance'])
        
        return jsonify({
            "success": True,
            "stores": nearby_stores[:5]  # Return 5 closest stores
        })
        
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
