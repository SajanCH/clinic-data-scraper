import requests
from bs4 import BeautifulSoup
import csv
import time
import re

# Base URL for the Wayback Machine
BASE_URL = "https://web.archive.org/web/20250708180027/https://www.myfootdr.com.au"

# List of regions to scrape
REGIONS = [
    "sunshine-coast",
    "brisbane",
    "gold-coast",
    "north-queensland",
    "central-queensland",
    "new-south-wales",
    "victoria",
    "south-australia",
    "western-australia",
    "northern-territory",
    "tasmania"
]

# Manual overrides for addresses when automatic extraction fails or is noisy
ADDRESS_OVERRIDES = {
    'Allsports Podiatry Noosa': 'Unit 4, 17 Sunshine Beach Rd\nNoosa QLD 4567'
}
def get_page_content(url):
    """Fetch page content with retry logic"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
    }
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            return response.text
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(1)
            else:
                print(f"  Error fetching URL {url}: {str(e)[:50]}")
                return None

def build_clinic_url(clinic_path):
    """Build a properly formatted clinic URL"""
    # Remove any extra /web/ parts
    clinic_path = clinic_path.lstrip('/')
    return f"{BASE_URL}/{clinic_path}"

def extract_clinics_from_region(region_name):
    """Extract all clinic links from a region page"""
    region_url = f"{BASE_URL}/our-clinics/regions/{region_name}/"
    print(f"Fetching region: {region_name}")
    
    content = get_page_content(region_url)
    if not content:
        print(f"  Failed to fetch region page")
        return []
    
    soup = BeautifulSoup(content, 'html.parser')
    clinics = []
    
    # Find all links that point to clinic pages
    for link in soup.find_all('a', href=True):
        href = link.get('href')
        text = link.get_text(strip=True)

        # If visible text is missing, try title/aria-label or nested headings
        if (not text or len(text) < 2):
            text = link.get('title') or link.get('aria-label') or ''
            if not text:
                nested = link.find(['h2', 'h3', 'h4'])
                if nested:
                    text = nested.get_text(strip=True)

        if not href or not text or len(text) < 2:
            continue

        # Skip obvious non-clinic links
        if text.strip() == 'Our Clinics':
            continue

        # Check if it's a clinic page link. Wayback hrefs often include '/web/<ts>/https://...'
        if '/our-clinics/' in href and '/regions/' not in href:
            # Try to extract the slug anywhere in the href (not only at the end)
            match = re.search(r'/our-clinics/([^/]+)/', href)
            clinic_slug = None
            if match:
                clinic_slug = match.group(1)
            else:
                # Fallback: extract text after the last '/our-clinics/' and take first segment
                try:
                    tail = href.split('/our-clinics/')[-1]
                    clinic_slug = tail.split('/')[0].strip()
                except Exception:
                    clinic_slug = None

            if clinic_slug:
                prefix_to_remove = 'https://web.archive.org/web/20250708180027/'
                clinic_url = build_clinic_url(f"our-clinics/{clinic_slug}/")
                clinic_url = clinic_url.replace(prefix_to_remove, '')
                clinics.append({'name': text, 'url': clinic_url})
    
    # Remove duplicates
    seen = set()
    unique_clinics = []
    for clinic in clinics:
        if clinic['url'] not in seen:
            seen.add(clinic['url'])
            unique_clinics.append(clinic)
    
    print(f"  Found {len(unique_clinics)} clinics")
    return unique_clinics

def extract_clinic_details(clinic_url, clinic_name):
    """Extract details from a clinic page"""
    try:
        content = get_page_content(clinic_url)
    except Exception as e:
        print(f"  Error fetching clinic page: {str(e)[:50]}")
        return None
    
    try:
        soup = BeautifulSoup(content, 'html.parser')
        text_content = soup.get_text()
    except Exception as e:
        print(f"  Error parsing clinic page HTML: {str(e)[:50]}")
        return None
    
    details = {
        'Name of Clinic': clinic_name,
        'Address': '',
        'Email': '',
        'Phone': '',
        'Services': ''
    }
    
    # Extract phone number
    phone_patterns = [
        r'Call\s+([\d\s\(\)\-\+]+)',
        r'[\(\s]?0[2-9][\d\s\(\)\-]{7,}',
    ]
    
    for pattern in phone_patterns:
        phone_match = re.search(pattern, text_content, re.IGNORECASE)
        if phone_match:
            phone_text = phone_match.group(1) if '(' in pattern else phone_match.group(0)
            phone_clean = re.sub(r'[^\d\s\(\)\-\+]', '', phone_text).strip()
            if phone_clean and len(phone_clean) > 5:
                details['Phone'] = phone_clean
                break
    
    # Extract email
    email_match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', text_content)
    if email_match:
        details['Email'] = email_match.group(0)
    
    # Extract address - use stricter pattern to find street + suburb + state + postcode
    # Pattern: unit/number + street + suburb line with state code + postcode
    address_patterns = [
        r'((?:Unit|Suite|No|Lot)[\s\d\w\-]*,\s*\d+[\w\s\.]+(?:St|Street|Rd|Road|Ave|Avenue|Dr|Drive|Lane|Ln|Crescent|Cres|Court|Ct|Pl|Place|Bvd|Boulevard)\s+[\w\s]+(?:QLD|NSW|VIC|WA|SA|NT|TAS|ACT)\s+\d{4})',
        r'(\d+[\s\w\-]*(?:St|Street|Rd|Road|Ave|Avenue|Dr|Drive|Lane|Ln|Crescent|Cres|Court|Ct|Pl|Place|Bvd|Boulevard)[\w\s]+(?:QLD|NSW|VIC|WA|SA|NT|TAS|ACT)\s+\d{4})',
    ]
    
    addr_text = ''
    
    # First try to find address in the full text with any of the patterns
    for pattern in address_patterns:
        address_match = re.search(pattern, text_content, re.IGNORECASE)
        if address_match:
            addr_text = address_match.group(1).strip()
            # Normalize newlines and multiple spaces
            addr_text = re.sub(r'\s+', ' ', addr_text)
            break
    
    details['Address'] = addr_text
    
    # Extract services from the "Services Available" section
    services = []
    
    # Find the "Services Available" heading (h2 containing "Services Available")
    services_heading = None
    for heading in soup.find_all(['h2', 'h3']):
        if 'Services Available' in heading.get_text():
            services_heading = heading
            break
    
    if services_heading:
        # Extract services from article elements that follow
        current = services_heading.find_next_sibling()
        while current:
            # Stop if we hit another h2 (new section)
            if current.name == 'h2':
                break
            
            # Look for article elements containing service info
            if current.name == 'article':
                # Try to find h3 heading inside the article
                h3 = current.find('h3')
                if h3:
                    service_text = h3.get_text(strip=True)
                    # Remove markdown link syntax like [Text](url) leaving just Text
                    service_text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', service_text)
                    if service_text and len(service_text) > 2:
                        services.append(service_text)
            
            current = current.find_next_sibling()
    
    details['Services'] = ', '.join(services) if services else ''
    
    # Apply manual overrides when available (fix noisy/missing addresses)
    override = ADDRESS_OVERRIDES.get(details['Name of Clinic'])
    if override:
        details['Address'] = override
    
    return details

def scrape_all_clinics():
    """Main scraping function"""
    print("Starting clinic data scraper...\n")
    all_clinics = []
    
    # Collect all clinics from all regions
    for region in REGIONS:
        try:
            clinics = extract_clinics_from_region(region)
            all_clinics.extend(clinics)
            time.sleep(0.5)
        except Exception as e:
            print(f"  Error in region {region}: {str(e)[:50]}")
    
    print(f"\n\nTotal clinics discovered: {len(all_clinics)}")
    print(f"all_clinics links: {all_clinics}\n")
    print("Now fetching individual clinic details...\n")
    
    # Extract details from each clinic
    clinic_data = []
    successful = 0
    failed = 0
    
    for i, clinic in enumerate(all_clinics, 1):
        clinic_name_short = clinic['name'][:45] if len(clinic['name']) > 45 else clinic['name']
        print(f"[{i:>3}/{len(all_clinics)}] {clinic_name_short:<47}", end=' ', flush=True)
        
        details = extract_clinic_details(clinic['url'], clinic['name'])
        # Include clinics even with partial data - just need at least one contact detail
        if details:
            clinic_data.append(details)
            successful += 1
            print("✓")
        else:
            failed += 1
            print("✗")
        
        time.sleep(0.3)
    
    # Save to CSV
    csv_file = '/Users/kittubittu/Documents/clinic-data-scraper/clinics.csv'
    if clinic_data:
        with open(csv_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['Name of Clinic', 'Address', 'Email', 'Phone', 'Services'])
            writer.writeheader()
            writer.writerows(clinic_data)
        print(f"\n\n{'='*60}")
        print(f"Successfully scraped data from {successful} clinics")
        print(f"Failed or incomplete: {failed} clinics")
        print(f"Data saved to: {csv_file}")
        print(f"{'='*60}")
    else:
        print("No clinic data found!")

if __name__ == "__main__":
    scrape_all_clinics()
