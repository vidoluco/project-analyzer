import streamlit as st
import os
from dotenv import load_dotenv
import PyPDF2
import requests
import json
# from google_auth_oauthlib.flow import Flow
# from google.oauth2.credentials import Credentials
# from googleapiclient.discovery import build
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, PageBreak
from reportlab.lib.units import inch
import tempfile
from pathlib import Path
import io
# import firebase_admin
# from firebase_admin import credentials, firestore
import time
import datetime
from google.cloud import storage
import uuid
import base64

# Load environment variables
load_dotenv()

# HARDCODED ENVIRONMENT SETTING
# Cambia questo valore manualmente quando passi da locale a produzione
# True = ambiente locale, False = ambiente di produzione (Streamlit Cloud)
IS_LOCAL_ENVIRONMENT = False

# Stampa debug all'avvio
print(f"Running with hardcoded environment: {'LOCAL' if IS_LOCAL_ENVIRONMENT else 'PRODUCTION'}")

# Initialize session state for file operations
if 'temp_files' not in st.session_state:
    st.session_state.temp_files = []

# Function to clean up temporary files
def cleanup_temp_files():
    for file_path in st.session_state.temp_files:
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except Exception as e:
            pass
    st.session_state.temp_files = []

# Set environment variables
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1' 
PERPLEXITY_API_KEY = os.getenv('PERPLEXITY_API_KEY')

# HARDCODED REDIRECT URIs
LOCAL_REDIRECT_URI = "http://localhost:8501/"
PRODUCTION_REDIRECT_URI = "https://crypto-project-analyzer.streamlit.app/"

# Set the redirect URI based on hardcoded environment setting
if IS_LOCAL_ENVIRONMENT:
    # Ambiente locale
    REDIRECT_URI = LOCAL_REDIRECT_URI
else:
    # Ambiente di produzione
    REDIRECT_URI = PRODUCTION_REDIRECT_URI

# Set Google Application Credentials
# os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = os.path.join(os.path.dirname(__file__), 'nova-gcp-infra-d3488d86e9fa.json')

# Initialize Firebase Admin SDK
# cred = credentials.Certificate('nova-gcp-infra-d3488d86e9fa.json')
# try:
#     app = firebase_admin.initialize_app(cred, {
#         'projectId': 'nova-gcp-infra'
#     })
# except ValueError:
#     app = firebase_admin.get_app()

# Initialize Firestore client
# db = firestore.Client(project='nova-gcp-infra', database='cryptoanalysisappusersdb')

# def check_user_access(email):
#     """Check if user's email exists in the Firestore database."""
#     try:
#         # Debug information
#         st.write(f"Checking access for email: {email}")
#         
#         # Query the users collection for the email
#         users_ref = db.collection('Users')
#         user_query = users_ref.where('email', '==', email).limit(1).get()
#         
#         # Print the query results for debugging
#         results = list(user_query)
#         
#         has_access = len(results) > 0
#         if not has_access:
#             st.warning(f"User {email} not registered to the system.")
#         else:
#             st.success(f"Access granted for {email}")
#         return has_access
#     except Exception as e:
#         st.error(f"Error checking user access: {str(e)}")
#         st.error(f"Current working directory: {os.getcwd()}")
#         st.error(f"Service account path: {os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')}")
#         return False

if not PERPLEXITY_API_KEY:
    st.error("Please set your PERPLEXITY_API_KEY in the .env file")
    st.stop()

# Initialize session state
if 'user' not in st.session_state:
    st.session_state.user = {"email": "temporary_user@example.com"}  # Utente temporaneo per accesso senza login

if 'messages' not in st.session_state:
    st.session_state.messages = []

if 'whitepaper_text' not in st.session_state:
    st.session_state.whitepaper_text = ""

# Initialize session state for usage limits and stored analyses
if 'analysis_count' not in st.session_state:
    st.session_state.analysis_count = 0

if 'scrape_count' not in st.session_state:
    st.session_state.scrape_count = 0

if 'stored_analyses' not in st.session_state:
    st.session_state.stored_analyses = []

if 'stored_scrapes' not in st.session_state:
    st.session_state.stored_scrapes = []

# Constants for usage limits
MAX_ANALYSES = 7
MAX_SCRAPES = 15

# Function to reset usage counts (e.g., for testing)
def reset_usage_counts():
    st.session_state.analysis_count = 0
    st.session_state.scrape_count = 0

# Function to convert PDF to base64 for browser storage
def get_pdf_as_base64(pdf_bytes):
    """Convert PDF bytes to base64 string for browser storage"""
    base64_pdf = base64.b64encode(pdf_bytes.read()).decode('utf-8')
    return base64_pdf

# Function to download content as PDF and get base64
def get_base64_pdf(content):
    """Create PDF and return as base64 string"""
    try:
        pdf_buffer = io.BytesIO()
        pdf = SimpleDocTemplate(
            pdf_buffer,
            pagesize=A4,
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=72
        )
        
        styles = getSampleStyleSheet()
        story = []
        
        for page in content:
            title = page.get('title', 'Untitled')
            story.append(Paragraph(title, styles['Heading1']))
            story.append(Spacer(1, 12))
            
            content_paragraphs = page['content'].split('\n')
            for paragraph in content_paragraphs:
                if paragraph.strip():
                    story.append(Paragraph(paragraph, styles['Normal']))
                    story.append(Spacer(1, 12))
            
            story.append(PageBreak())
        
        pdf.build(story)
        pdf_buffer.seek(0)
        
        # Convert to base64
        base64_pdf = base64.b64encode(pdf_buffer.getvalue()).decode('utf-8')
        return base64_pdf
    except Exception as e:
        st.error(f"Error creating PDF: {str(e)}")
        return None

# Function to save analysis to browser's local storage via Streamlit
def save_analysis_locally(project_name, analysis_data):
    """Save analysis data to browser's localStorage using Streamlit"""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Create analysis record
    analysis_record = {
        "project_name": project_name,
        "timestamp": timestamp,
        "data": analysis_data
    }
    
    # Add to session state
    st.session_state.stored_analyses.append(analysis_record)
    
    # Limit stored analyses to MAX_ANALYSES
    if len(st.session_state.stored_analyses) > MAX_ANALYSES:
        st.session_state.stored_analyses.pop(0)  # Remove oldest
    
    # Use JavaScript to store in browser's localStorage
    analysis_json = json.dumps(analysis_record)
    js_code = f"""
    <script>
        const analysisData = {analysis_json};
        const storedAnalyses = JSON.parse(localStorage.getItem('cryptoAnalyses') || '[]');
        storedAnalyses.push(analysisData);
        
        // Limit to {MAX_ANALYSES} analyses
        while (storedAnalyses.length > {MAX_ANALYSES}) {{
            storedAnalyses.shift();  // Remove oldest
        }}
        
        localStorage.setItem('cryptoAnalyses', JSON.stringify(storedAnalyses));
    </script>
    """
    st.components.v1.html(js_code, height=0)
    
    return True

# Function to save scrape to browser's local storage
def save_scrape_locally(url, content_base64):
    """Save scraped content to browser's localStorage"""
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    # Create scrape record
    scrape_record = {
        "url": url,
        "timestamp": timestamp,
        "content_base64": content_base64
    }
    
    # Add to session state
    st.session_state.stored_scrapes.append(scrape_record)
    
    # Limit stored scrapes to MAX_SCRAPES
    if len(st.session_state.stored_scrapes) > MAX_SCRAPES:
        st.session_state.stored_scrapes.pop(0)  # Remove oldest
    
    # Use JavaScript to store in browser's localStorage
    # Note: Only storing metadata and URL in localStorage due to size constraints
    scrape_metadata = {
        "url": url,
        "timestamp": timestamp
    }
    js_code = f"""
    <script>
        const scrapeData = {json.dumps(scrape_metadata)};
        const storedScrapes = JSON.parse(localStorage.getItem('cryptoScrapes') || '[]');
        storedScrapes.push(scrapeData);
        
        // Limit to {MAX_SCRAPES} scrapes
        while (storedScrapes.length > {MAX_SCRAPES}) {{
            storedScrapes.shift();  // Remove oldest
        }}
        
        localStorage.setItem('cryptoScrapes', JSON.stringify(storedScrapes));
    </script>
    """
    st.components.v1.html(js_code, height=0)
    
    return True

# Function to load stored analyses from browser's localStorage
def load_stored_analyses():
    """Load analyses from browser's localStorage"""
    # Use JavaScript to retrieve data and set it to element that we can read
    js_code = """
    <script>
        const storedAnalyses = JSON.parse(localStorage.getItem('cryptoAnalyses') || '[]');
        document.getElementById('analyses-data').textContent = JSON.stringify(storedAnalyses);
    </script>
    <div id="analyses-data" style="display:none;"></div>
    """
    
    # Create a container for JavaScript to write to
    html_container = st.empty()
    html_container.components.v1.html(js_code, height=0)
    
    # In a real implementation, we would read from the element
    # For now, use session state (would normally be populated from the element)
    return st.session_state.stored_analyses

# Function to load stored scrapes from browser's localStorage
def load_stored_scrapes():
    """Load scrapes from browser's localStorage"""
    # Use JavaScript to retrieve data
    js_code = """
    <script>
        const storedScrapes = JSON.parse(localStorage.getItem('cryptoScrapes') || '[]');
        document.getElementById('scrapes-data').textContent = JSON.stringify(storedScrapes);
    </script>
    <div id="scrapes-data" style="display:none;"></div>
    """
    
    # Create a container for JavaScript to write to
    html_container = st.empty()
    html_container.components.v1.html(js_code, height=0)
    
    # In a real implementation, we would read from the element
    # For now, use session state (would normally be populated from the element)
    return st.session_state.stored_scrapes

def is_gitbook_url(url):
    """Check if the URL is a GitBook documentation."""
    try:
        response = requests.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Modern GitBook elements
        gitbook_indicators = [
            '.gitbook-root',  # Classic GitBook
            'meta[content*="GitBook"]',  # GitBook meta tag
            '.with-summary',  # GitBook class
            '#__GITBOOK__',  # Modern GitBook root
            '.reset-3c756112--content-6f63cbbe',  # Modern GitBook content
            '.book-summary',  # Classic GitBook summary
            'script[src*="gitbook"]',  # GitBook scripts
            'link[href*="gitbook"]'  # GitBook styles
        ]
        
        # Check for GitBook indicators
        for indicator in gitbook_indicators:
            if soup.select(indicator):
                return True
        
        # Check URL patterns
        gitbook_domains = ['gitbook.io', 'docs.', '.gitbook.']
        return any(domain in url.lower() for domain in gitbook_domains)
    except:
        return False

def is_pdf_url(url, var_attacker_addr=None):
    """Check if the URL points to a PDF file or PDF viewer."""
    try:
        # Direct PDF check
        response = requests.head(url, allow_redirects=True)
        content_type = response.headers.get('content-type', '').lower()
        if 'application/pdf' in content_type:
            return True
            
        # Check if it's a PDF viewer page
        response = requests.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Common PDF viewer indicators
        pdf_indicators = [
            'embed[type="application/pdf"]',
            'object[type="application/pdf"]',
            'iframe[src*=".pdf"]',
            '.pdf-viewer',
            '#pdf-viewer',
            'meta[content*="pdf"]',
            'a[href$=".pdf"]',
            '[src$=".pdf"]',
            '[data-src$=".pdf"]'
        ]
        
        for indicator in pdf_indicators:
            elements = soup.select(indicator)
            if elements:
                for element in elements:
                    # Try different attributes that might contain the PDF URL
                    for attr in ['src', 'href', 'data', 'data-src']:
                        pdf_url = element.get(attr)
                        if pdf_url:
                            if pdf_url.lower().endswith('.pdf'):
                                return urljoin(url, pdf_url)
                            elif 'pdf' in pdf_url.lower():
                                # Try to follow the URL to see if it redirects to a PDF
                                try:
                                    pdf_response = requests.head(urljoin(url, pdf_url), allow_redirects=True)
                                    if 'application/pdf' in pdf_response.headers.get('content-type', '').lower():
                                        return pdf_response.url
                                except:
                                    continue
        
        # Check for PDF in page content
        pdf_links = soup.select('a[href*=".pdf"], a[href*="pdf"]')
        if pdf_links:
            return urljoin(url, pdf_links[0]['href'])
            
        return False
    except Exception as e:
        st.error(f"Error checking PDF URL: {str(e)}")
        return False

def download_pdf(url):
    """Download PDF file from URL."""
    try:
        response = requests.get(url)
        return io.BytesIO(response.content)
    except Exception as e:
        st.error(f"Error downloading PDF: {str(e)}")
        return None

def scrape_gitbook_page(url):
    """Scrape content from a single GitBook page."""
    try:
        response = requests.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Try different content selectors for various GitBook versions
        content_selectors = [
            'main article',  # Modern GitBook main content
            '.markdown-section',  # Modern GitBook
            '.page-inner',  # Classic GitBook
            '.reset-3c756112--content-6f63cbbe',  # Modern GitBook specific
            '.documentation-content',  # Common documentation class
            'main',  # Main content area
            '.content'  # Generic content
        ]
        
        content = None
        for selector in content_selectors:
            content = soup.select_one(selector)
            if content:
                break
        
        if content:
            # Remove unnecessary elements
            for element in content.select('.js-toc-content, .js-toc, nav, header, footer, .toolbar-button, [class*="gitbook-"]'):
                element.decompose()
            
            # Get title from various possible locations
            title = None
            title_selectors = [
                'h1:first-of-type',
                '.page-title',
                '.header-title',
                'title',
                '[class*="heading"]'
            ]
            
            for selector in title_selectors:
                title_elem = soup.select_one(selector)
                if title_elem:
                    title = title_elem.get_text(strip=True)
                    break
            
            # Extract images
            images = []
            for img in content.find_all('img'):
                src = img.get('src')
                if src:
                    if src.startswith('//'):
                        src = 'https:' + src
                    elif src.startswith('/'):
                        src = urljoin(url, src)
                    else:
                        src = urljoin(url, src)
                    
                    alt = img.get('alt', '')
                    images.append({
                        'src': src,
                        'alt': alt
                    })
            
            return {
                'title': title or soup.title.string if soup.title else '',
                'content': content.get_text(separator='\n', strip=True),
                'images': images
            }
        return None
    except Exception as e:
        st.error(f"Error scraping page {url}: {str(e)}")
        return None

def get_gitbook_menu(url):
    """Extract menu items from GitBook."""
    try:
        response = requests.get(url)
        soup = BeautifulSoup(response.text, 'html.parser')
        
        menu_items = []
        
        def extract_menu_items(container):
            items = []
            if not container:
                return items
                
            # Look for links in the container
            for link in container.select('a[href]'):
                href = link.get('href')
                if href and not href.startswith(('#', 'javascript:', 'mailto:')):
                    # Clean up the URL
                    if href.startswith('//'):
                        href = 'https:' + href
                    elif href.startswith('/'):
                        href = urljoin(url, href)
                    else:
                        href = urljoin(url, href)
                    
                    # Get the title, looking for emoji and text separately
                    title_parts = []
                    emoji = link.select_one('.font-emoji')
                    if emoji:
                        title_parts.append(emoji.get_text(strip=True))
                    
                    # Get the text content excluding emoji
                    text_nodes = [node for node in link.strings if node.strip()]
                    text = ' '.join(text_nodes)
                    if text:
                        title_parts.append(text)
                    
                    title = ' '.join(filter(None, title_parts))
                    
                    if title and href and not any(item['url'] == href for item in items):
                        items.append({
                            'title': title,
                            'url': href,
                            'level': len(link.find_parents(['li', 'ul']))
                        })
            
            # Look for nested menus
            for submenu in container.select('ul, [class*="submenu"], [class*="children"]'):
                items.extend(extract_menu_items(submenu))
            
            return items

        # Try different menu containers
        menu_selectors = [
            'nav',  # Generic navigation
            'aside',  # Sidebar
            '[class*="menu"]',  # Any menu container
            '[class*="sidebar"]',  # Any sidebar container
            '[class*="navigation"]',  # Navigation container
            '.book-summary',  # Classic GitBook
            '[class*="table-of-contents"]'  # ToC container
        ]
        
        for selector in menu_selectors:
            menu_containers = soup.select(selector)
            for container in menu_containers:
                items = extract_menu_items(container)
                if items:
                    menu_items.extend(items)
        
        # Remove duplicates while preserving order
        seen_urls = set()
        unique_items = []
        for item in menu_items:
            if item['url'] not in seen_urls:
                seen_urls.add(item['url'])
                unique_items.append(item)
        
        # Sort by level and URL to maintain hierarchy
        unique_items.sort(key=lambda x: (x.get('level', 0), x['url']))
        
        if not unique_items:
            st.warning("No menu structure found. Attempting to extract links from content...")
            # Try to find links in the main content as a fallback
            content_containers = soup.select('main, article, .content, [class*="markdown"]')
            for container in content_containers:
                items = extract_menu_items(container)
                if items:
                    unique_items.extend(items)
        
        return unique_items
    except Exception as e:
        st.error(f"Error getting menu: {str(e)}")
        return []

def scrape_gitbook(url):
    """Scrape entire GitBook and return content."""
    menu_items = get_gitbook_menu(url)
    content = []
    
    if not menu_items:
        # If no menu items found, try to scrape the main page
        st.info("No menu found. Scraping main page...")
        page_content = scrape_gitbook_page(url)
        if page_content:
            content.append(page_content)
            return content
        else:
            st.error("Could not extract content from the page.")
            return None
    
    # Create progress bar
    progress_text = "Scraping pages..."
    progress_bar = st.progress(0, text=progress_text)
    total_items = len(menu_items)
    
    try:
        st.write(f"Found {total_items} pages to scrape")
        for i, item in enumerate(menu_items):
            # Update progress
            current_progress = (i + 1) / total_items
            progress_bar.progress(current_progress, text=f"Scraping: {item['title']} ({i+1}/{total_items})")
            
            # Add level indicator for nested structure
            level_indicator = "  " * item.get('level', 0) + "└─ " if item.get('level', 0) > 0 else ""
            
            # Scrape the page
            page_content = scrape_gitbook_page(item['url'])
            if page_content:
                content.append(page_content)
                st.success(f"{level_indicator}✓ {item['title']}")
            else:
                st.warning(f"{level_indicator}⚠️ Failed to scrape: {item['title']}")
                
            # Small delay to avoid overwhelming the server
            time.sleep(0.5)
            
    except Exception as e:
        st.error(f"Error during scraping: {str(e)}")
    finally:
        # Clear progress bar
        progress_bar.empty()
    
    if not content:
        st.error("No content could be extracted from any page.")
        return None
    
    st.success(f"Successfully scraped {len(content)} pages!")
    return content

def create_pdf_from_content(content):
    """Create PDF from scraped content using ReportLab."""
    try:
        # Create PDF buffer
        pdf_buffer = io.BytesIO()
        
        # Create the PDF document
        doc = SimpleDocTemplate(
            pdf_buffer,
            pagesize=A4,
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=72
        )
        
        # Get styles
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            spaceAfter=30
        )
        body_style = ParagraphStyle(
            'CustomBody',
            parent=styles['Normal'],
            fontSize=12,
            spaceAfter=12
        )
        
        # Create story (content)
        story = []
        
        for page in content:
            # Add title
            title = page.get('title', 'Untitled')
            story.append(Paragraph(title, title_style))
            story.append(Spacer(1, 12))
            
            # Add images if any
            if 'images' in page and page['images']:
                for img in page['images']:
                    try:
                        # Download image
                        img_response = requests.get(img['src'])
                        if img_response.status_code == 200:
                            img_data = io.BytesIO(img_response.content)
                            img_width = 6 * inch  # 6 inches width
                            story.append(Image(img_data, width=img_width, height=img_width * 0.75))
                            story.append(Spacer(1, 12))
                    except Exception as e:
                        st.warning(f"Could not add image: {str(e)}")
            
            # Add content
            content_paragraphs = page['content'].split('\n')
            for paragraph in content_paragraphs:
                if paragraph.strip():
                    story.append(Paragraph(paragraph, body_style))
                    story.append(Spacer(1, 12))
            
            # Add page break
            story.append(Spacer(1, 20))
        
        # Build PDF
        doc.build(story)
        pdf_buffer.seek(0)
        return pdf_buffer
    except Exception as e:
        st.error(f"Error creating PDF: {str(e)}")
        return None

def extract_text_from_pdf(pdf_file):
    pdf_reader = PyPDF2.PdfReader(pdf_file)
    text = ""
    for page in pdf_reader.pages:
        text += page.extract_text()
    return text

# Funzione di autenticazione commentata - sarà implementata in una release futura
# def auth_flow():
#     try:
#         # Use hardcoded environment setting
#         is_local = IS_LOCAL_ENVIRONMENT
#         
#         # Set the correct redirect URI based on hardcoded environment setting
#         redirect_uri = LOCAL_REDIRECT_URI if is_local else PRODUCTION_REDIRECT_URI
#         
#         # Create flow instance
#         flow = Flow.from_client_secrets_file(
#             'client_secret_487298376198-140i5gfel69hkaue4jqn27kjgo3s74k1.apps.googleusercontent.com.json',
#             scopes=['openid', 'https://www.googleapis.com/auth/userinfo.profile', 'https://www.googleapis.com/auth/userinfo.email'],
#             redirect_uri=redirect_uri
#         )
#
#         # Get authorization code from URL parameters
#         auth_code = st.query_params.get("code")
#         
#         if not auth_code:
#             # Generate authorization URL
#             auth_url, state = flow.authorization_url(
#                 access_type='offline',
#                 include_granted_scopes='true',
#                 prompt='consent'  # Force consent screen
#             )
#             st.markdown(f'[Login with Google]({auth_url})')
#             return None
#
#         # Exchange auth code for credentials
#         try:
#             flow.fetch_token(code=auth_code)
#             credentials = flow.credentials
#
#             # Get user info using credentials
#             service = build('oauth2', 'v2', credentials=credentials)
#             user_info = service.userinfo().get().execute()
#
#             # Check if user exists in allowed_emails.txt
#             with open('allowed_emails.txt', 'r') as f:
#                 allowed_emails = [email.strip() for email in f.readlines()]
#             
#             if user_info['email'] not in allowed_emails:
#                 st.error("Access denied. Your email is not authorized to use this application.")
#                 return None
#                 
#             # Clear the URL parameters after successful authentication
#             if not is_local:
#                 # In production, use JavaScript to remove the query params
#                 st.markdown("""
#                 <script>
#                 // Remove query parameters and redirect to base URL
#                 if (window.location.search) {
#                     var baseUrl = window.location.href.split('?')[0];
#                     window.history.replaceState({}, document.title, baseUrl);
#                 }
#                 </script>
#                 """, unsafe_allow_html=True)
#             else:
#                 # In local environment, use Streamlit's API
#                 st.query_params.clear()
#                 
#             return user_info
#         except Exception as e:
#             st.error(f"Error during authentication: {str(e)}")
#             # Clear URL parameters to allow retrying
#             if is_local:
#                 st.query_params.clear()
#             return None
#
#     except Exception as e:
#         st.error(f"Error in auth flow: {str(e)}")
#         return None

def extract_score_from_analysis(analysis_text, max_points):
    # Look for common score patterns in the text
    score_patterns = [
        r"Overall Score:?\s*(\d+\.?\d*)/\d+",
        r"Total Score:?\s*(\d+\.?\d*)/\d+",
        r"Final Score:?\s*(\d+\.?\d*)/\d+",
        r"Score:?\s*(\d+\.?\d*)/\d+",
        r"(\d+\.?\d*)/10\s*(?:points)?(?:\.|$)",
        r"Score Breakdown:.*?Total:?\s*(\d+\.?\d*)/\d+"
    ]
    
    # First try to find an overall/total/final score
    for pattern in score_patterns:
        match = re.search(pattern, analysis_text, re.DOTALL | re.IGNORECASE)
        if match:
            score = float(match.group(1))
            # Convert the score to the appropriate scale if needed
            if score <= 10:  # If score is out of 10
                score = (score / 10) * max_points
            elif score <= 100:  # If score is out of 100
                score = (score / 100) * max_points
            return round(score, 1)
    
    # If no overall score found, try to extract individual scores and average them
    individual_scores = []
    score_lines = re.findall(r"(?:Score|Rating):\s*(\d+\.?\d*)/\d+", analysis_text, re.IGNORECASE)
    if score_lines:
        for score in score_lines:
            individual_scores.append(float(score))
    
    # Also look for numbered scores in format "1. Something: 8/10"
    numbered_scores = re.findall(r"\d+\.\s+[^:]+:\s*(\d+\.?\d*)/\d+", analysis_text)
    if numbered_scores:
        for score in numbered_scores:
            individual_scores.append(float(score))
    
    # If we found any individual scores, average them
    if individual_scores:
        avg_score = sum(individual_scores) / len(individual_scores)
        return round((avg_score / 10) * max_points, 1)
    
    # Last resort: Look for explicit scores in format "Score (8/10)"
    explicit_scores = re.findall(r"Score\s*\((\d+\.?\d*)/\d+\)", analysis_text)
    if explicit_scores:
        total = sum(float(score) for score in explicit_scores)
        avg_score = total / len(explicit_scores)
        return round((avg_score / 10) * max_points, 1)
    
    return 0  # Default score if no pattern is found

def analyze_with_perplexity(text, aspect, max_points):
    url = "https://api.perplexity.ai/chat/completions"
    messages = [
        {"role": "system", "content": f"You are an expert analyst evaluating blockchain and cryptocurrency projects. For the {aspect} aspect, provide a detailed analysis with clear scoring breakdowns. Always include an explicit overall score out of 10 at the end of your analysis, formatted as 'Overall Score: X/10'."},
        {"role": "user", "content": f"Based on this whitepaper text, analyze the {aspect} aspect. Provide a detailed explanation with specific scoring breakdowns for each sub-aspect, and conclude with an explicit overall score out of 10: {text[:4000]}"}
    ]
    payload = {"model": "sonar-pro", "messages": messages, "temperature": 0.2}
    headers = {"Authorization": f"Bearer {PERPLEXITY_API_KEY}", "Content-Type": "application/json"}
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        analysis = response.json()['choices'][0]['message']['content']
        score = extract_score_from_analysis(analysis, max_points)
        if score == 0:
            messages.append({"role": "user", "content": "Please provide an explicit overall score out of 10 for this aspect."})
            response = requests.post(url, json=payload, headers=headers)
            response.raise_for_status()
            additional_response = response.json()['choices'][0]['message']['content']
            analysis += "\n\n" + additional_response
            score = extract_score_from_analysis(analysis, max_points)
        return analysis, score
    except Exception as e:
        return f"Error in analysis: {str(e)}", 0

def chat_with_perplexity(user_message, context):
    url = "https://api.perplexity.ai/chat/completions"
    
    messages = [
        {"role": "system", "content": "You are an expert analyst helping to analyze a whitepaper. Use the context provided to answer questions accurately and concisely."},
        {"role": "user", "content": f"Context from whitepaper:\n{context}\n\nUser question: {user_message}"}
    ]
    
    payload = {
        "model": "sonar-pro",
        "messages": messages,
        "temperature": 0.7
    }
    
    headers = {
        "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content']
    except Exception as e:
        return f"Error: {str(e)}"

def analyze_coinmarketcap_data(project_name):
    url = "https://api.perplexity.ai/chat/completions"
    messages = [
        {"role": "system", "content": "You are a cryptocurrency market data analyst. Search and analyze CoinMarketCap data for the specified project."},
        {"role": "user", "content": f"Search and analyze CoinMarketCap data for {project_name}. Include price, market cap, volume, trends, and key metrics."}
    ]
    payload = {"model": "sonar-pro", "messages": messages, "temperature": 0.3}
    headers = {"Authorization": f"Bearer {PERPLEXITY_API_KEY}", "Content-Type": "application/json"}
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content']
    except Exception as e:
        return f"Error in CoinMarketCap analysis: {str(e)}"

def analyze_reddit_sentiment(project_name):
    url = "https://api.perplexity.ai/chat/completions"
    messages = [
        {"role": "system", "content": "You are a social media analyst specializing in cryptocurrency communities."},
        {"role": "user", "content": f"Analyze Reddit discussions about {project_name}. Include community sentiment, discussions, and trends."}
    ]
    payload = {"model": "sonar-pro", "messages": messages, "temperature": 0.3}
    headers = {"Authorization": f"Bearer {PERPLEXITY_API_KEY}", "Content-Type": "application/json"}
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content']
    except Exception as e:
        return f"Error in Reddit analysis: {str(e)}"

def analyze_market_sentiment(project_name):
    url = "https://api.perplexity.ai/chat/completions"
    messages = [
        {"role": "system", "content": "You are a cryptocurrency market analyst."},
        {"role": "user", "content": f"Analyze market sentiment and reputation of {project_name}. Include social media presence, developments, and market trends."}
    ]
    payload = {"model": "sonar-pro", "messages": messages, "temperature": 0.7}
    headers = {"Authorization": f"Bearer {PERPLEXITY_API_KEY}", "Content-Type": "application/json"}
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content']
    except Exception as e:
        return f"Error in market analysis: {str(e)}"

def extract_project_name(text):
    url = "https://api.perplexity.ai/chat/completions"
    messages = [
        {"role": "system", "content": "You are an expert at analyzing whitepapers. Extract the main project/token name from the whitepaper text. Return ONLY the name, nothing else."},
        {"role": "user", "content": f"What is the name of the project/token described in this whitepaper? Return ONLY the name: {text[:2000]}"}
    ]
    payload = {"model": "sonar-pro", "messages": messages, "temperature": 0.1}
    headers = {"Authorization": f"Bearer {PERPLEXITY_API_KEY}", "Content-Type": "application/json"}
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content'].strip()
    except Exception as e:
        return None

# Function to generate full analysis PDF
def generate_analysis_pdf(project_name, whitepaper_text, tokenomics_analysis, tokenomics_score, 
                          tech_analysis, tech_score, market_analysis, market_score, 
                          team_analysis, team_score, total_score, 
                          coinmarketcap_data, reddit_sentiment, market_sentiment):
    """Create a comprehensive PDF report of the analysis"""
    try:
        # Create PDF buffer
        pdf_buffer = io.BytesIO()
        
        # Create the PDF document
        doc = SimpleDocTemplate(
            pdf_buffer,
            pagesize=A4,
            rightMargin=72,
            leftMargin=72,
            topMargin=72,
            bottomMargin=72
        )
        
        # Get styles
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'Title',
            parent=styles['Heading1'],
            fontSize=24,
            spaceAfter=30,
            alignment=1  # Center alignment
        )
        
        heading_style = ParagraphStyle(
            'Heading',
            parent=styles['Heading2'],
            fontSize=18,
            spaceAfter=12
        )
        
        subheading_style = ParagraphStyle(
            'Subheading',
            parent=styles['Heading3'],
            fontSize=14,
            spaceAfter=10
        )
        
        body_style = ParagraphStyle(
            'Body',
            parent=styles['Normal'],
            fontSize=10,
            spaceAfter=8
        )
        
        score_style = ParagraphStyle(
            'Score',
            parent=styles['Heading2'],
            fontSize=16,
            textColor=colors.blue,
            spaceAfter=12
        )
        
        # Create story (content)
        story = []
        
        # Add title and date
        current_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        story.append(Paragraph(f"Crypto Analysis Report: {project_name}", title_style))
        story.append(Paragraph(f"Generated on: {current_date}", body_style))
        story.append(Spacer(1, 30))
        
        # Add total score
        story.append(Paragraph(f"Total Project Score: {total_score}/100", score_style))
        story.append(Spacer(1, 20))
        
        # Add tokenomics section
        story.append(Paragraph("Tokenomics Analysis", heading_style))
        story.append(Paragraph(f"Score: {tokenomics_score}/30", score_style))
        story.append(Paragraph(tokenomics_analysis, body_style))
        story.append(PageBreak())
        
        # Add technology section
        story.append(Paragraph("Technology Analysis", heading_style))
        story.append(Paragraph(f"Score: {tech_score}/30", score_style))
        story.append(Paragraph(tech_analysis, body_style))
        story.append(PageBreak())
        
        # Add market section
        story.append(Paragraph("Market Potential Analysis", heading_style))
        story.append(Paragraph(f"Score: {market_score}/20", score_style))
        story.append(Paragraph(market_analysis, body_style))
        story.append(PageBreak())
        
        # Add team section
        story.append(Paragraph("Team Analysis", heading_style))
        story.append(Paragraph(f"Score: {team_score}/20", score_style))
        story.append(Paragraph(team_analysis, body_style))
        story.append(PageBreak())
        
        # Add additional market data
        story.append(Paragraph("Additional Market Data", heading_style))
        
        story.append(Paragraph("CoinMarketCap Analysis", subheading_style))
        story.append(Paragraph(coinmarketcap_data, body_style))
        story.append(Spacer(1, 15))
        
        story.append(Paragraph("Reddit Sentiment Analysis", subheading_style))
        story.append(Paragraph(reddit_sentiment, body_style))
        story.append(Spacer(1, 15))
        
        story.append(Paragraph("Market Sentiment Analysis", subheading_style))
        story.append(Paragraph(market_sentiment, body_style))
        
        # Build PDF
        doc.build(story)
        pdf_buffer.seek(0)
        return pdf_buffer
    except Exception as e:
        st.error(f"Error creating analysis PDF: {str(e)}")
        return None

# Function to upload to GCS bucket
def upload_to_gcs(pdf_content, project_name):
    """Upload the analysis PDF to Google Cloud Storage bucket"""
    try:
        # Initialize GCS client
        storage_client = storage.Client()
        
        # Get bucket name from environment variable or use default
        bucket_path = os.getenv('GCS_BUCKET_NAME', 'crypto-analysis-storage/analysis_outputs')
        
        # Split bucket path if it contains subdirectories
        if '/' in bucket_path:
            bucket_name = bucket_path.split('/')[0]
            prefix = '/'.join(bucket_path.split('/')[1:])
        else:
            bucket_name = bucket_path
            prefix = ""
        
        # Get the bucket
        bucket = storage_client.bucket(bucket_name)
        
        # Generate a unique filename
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = uuid.uuid4().hex[:8]
        sanitized_project_name = ''.join(e for e in project_name if e.isalnum() or e == '_' or e == '-').lower()
        filename = f"analysis_{sanitized_project_name}_{timestamp}_{unique_id}.pdf"
        
        # Create a full path with prefix if it exists
        full_path = f"{prefix}/{filename}" if prefix else filename
        
        # Create a new blob
        blob = bucket.blob(full_path)
        
        # Upload the PDF content
        blob.upload_from_file(pdf_content, content_type='application/pdf')
        
        # Get the public URL
        url = f"https://storage.googleapis.com/{bucket_name}/{full_path}"
        
        return url
    except Exception as e:
        st.error(f"Error uploading to GCS: {str(e)}")
        return None

def main():
    try:            
        # Initialize session state for authentication
        # if 'authentication_state' not in st.session_state:
        #     st.session_state.authentication_state = None
        if 'user' not in st.session_state:
            st.session_state.user = {"email": "temporary_user@example.com"}  # Utente temporaneo per accesso senza login
        if 'messages' not in st.session_state:
            st.session_state.messages = []
        if 'whitepaper_text' not in st.session_state:
            st.session_state.whitepaper_text = ""

        # Custom CSS for styling
        st.markdown("""
            <style>
            /* Main theme colors */
            :root {
                --nova-primary: #0A2540;
                --nova-secondary: #00A6FF;
                --nova-accent: #FF6B6B;
                --nova-background: #0F172A;
                --nova-surface: #1E293B;
                --nova-text: #E2E8F0;
                --nova-text-secondary: #94A3B8;
                --nova-success: #10B981;
                --nova-warning: #F59E0B;
                --nova-error: #EF4444;
                --nova-info: #3B82F6;
            }
            
            /* Hide Streamlit branding */
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            
            /* Global styles */
            .stApp {
                background: linear-gradient(135deg, var(--nova-background), var(--nova-surface)) !important;
                color: var(--nova-text) !important;
            }
            
            /* Header styling */
            div[data-testid="stHeader"] {
                background: none;
            }
            
            .main-header {
                background: linear-gradient(135deg, rgba(10, 37, 64, 0.95) 0%, rgba(0, 166, 255, 0.95) 100%);
                padding: 3rem 2rem;
                border-radius: 20px;
                color: white;
                text-align: center;
                margin: 1rem 0 2rem 0;
                box-shadow: 0 8px 32px rgba(0, 166, 255, 0.15);
                backdrop-filter: blur(10px);
                border: 1px solid rgba(255, 255, 255, 0.1);
            }
            
            .main-header h1 {
                font-size: 3rem;
                margin-bottom: 1rem;
                font-weight: 700;
                background: linear-gradient(to right, #fff, #E2E8F0);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
                text-shadow: 0 2px 10px rgba(0, 0, 0, 0.2);
            }
            
            .main-header p {
                font-size: 1.2rem;
                opacity: 0.9;
                max-width: 600px;
                margin: 0 auto;
                line-height: 1.6;
            }
            
            /* Sidebar styling */
            section[data-testid="stSidebar"] {
                background-color: var(--nova-surface);
                padding: 2rem 1rem;
                border-right: 1px solid rgba(255, 255, 255, 0.1);
            }
            
            section[data-testid="stSidebar"] > div {
                padding-top: 0;
            }
            
            section[data-testid="stSidebar"] .stRadio > label {
                color: var(--nova-text) !important;
            }
            
            section[data-testid="stSidebar"] .stRadio > div {
                color: var(--nova-text-secondary) !important;
            }
            
            /* Message styling */
            .element-container div[data-testid="stMarkdownContainer"] > div {
                padding: 1rem;
                border-radius: 12px;
                margin: 1rem 0;
                background: var(--nova-surface);
                border: 1px solid rgba(255, 255, 255, 0.1);
                box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
            }
            
            /* Success message */
            .stSuccess {
                background: linear-gradient(135deg, rgba(16, 185, 129, 0.2), rgba(16, 185, 129, 0.1)) !important;
                border: 1px solid var(--nova-success) !important;
                color: #A7F3D0 !important;
                padding: 1rem !important;
                border-radius: 12px !important;
                margin: 1rem 0 !important;
                box-shadow: 0 4px 15px rgba(16, 185, 129, 0.1) !important;
            }
            
            /* Warning message */
            .stWarning {
                background: linear-gradient(135deg, rgba(245, 158, 11, 0.2), rgba(245, 158, 11, 0.1)) !important;
                border: 1px solid var(--nova-warning) !important;
                color: #FCD34D !important;
                padding: 1rem !important;
                border-radius: 12px !important;
                margin: 1rem 0 !important;
                box-shadow: 0 4px 15px rgba(245, 158, 11, 0.1) !important;
            }
            
            /* Error message */
            .stError {
                background: linear-gradient(135deg, rgba(239, 68, 68, 0.2), rgba(239, 68, 68, 0.1)) !important;
                border: 1px solid var(--nova-error) !important;
                color: #FCA5A5 !important;
                padding: 1rem !important;
                border-radius: 12px !important;
                margin: 1rem 0 !important;
                box-shadow: 0 4px 15px rgba(239, 68, 68, 0.1) !important;
            }
            
            /* Info message */
            .stInfo {
                background: linear-gradient(135deg, rgba(59, 130, 246, 0.2), rgba(59, 130, 246, 0.1)) !important;
                border: 1px solid var(--nova-info) !important;
                color: #93C5FD !important;
                padding: 1rem !important;
                border-radius: 12px !important;
                margin: 1rem 0 !important;
                box-shadow: 0 4px 15px rgba(59, 130, 246, 0.1) !important;
            }
            
            /* Login button styling */
            a[href*="accounts.google.com"] {
                display: inline-block;
                background: linear-gradient(135deg, #0A2540, #00A6FF);
                color: white !important;
                text-decoration: none !important;
                padding: 1rem 2rem;
                border-radius: 12px;
                font-weight: 500;
                margin-top: 2rem;
                transition: all 0.3s ease;
                border: 1px solid rgba(255, 255, 255, 0.1);
                box-shadow: 0 4px 15px rgba(0, 166, 255, 0.2);
            }
            
            a[href*="accounts.google.com"]:hover {
                transform: translateY(-2px);
                box-shadow: 0 8px 25px rgba(0, 166, 255, 0.3);
            }
            
            /* File uploader styling */
            .stUploadButton > button {
                background: var(--nova-surface) !important;
                color: var(--nova-text) !important;
                border: 2px dashed rgba(0, 166, 255, 0.5) !important;
                border-radius: 12px !important;
                padding: 2rem !important;
                width: 100% !important;
                transition: all 0.3s ease !important;
            }
            
            .stUploadButton > button:hover {
                border-color: var(--nova-secondary) !important;
                background: rgba(0, 166, 255, 0.1) !important;
                transform: translateY(-2px);
            }
            
            /* Button styling */
            .stButton > button {
                background: linear-gradient(135deg, #0A2540, #00A6FF) !important;
                color: white !important;
                border: none !important;
                padding: 0.75rem 2rem !important;
                border-radius: 12px !important;
                font-weight: 500 !important;
                transition: all 0.3s ease !important;
                text-transform: uppercase !important;
                letter-spacing: 0.5px !important;
            }
            
            .stButton > button:hover {
                transform: translateY(-2px);
                box-shadow: 0 8px 25px rgba(0, 166, 255, 0.3) !important;
            }
            
            /* Input styling */
            .stTextInput > div > div {
                background: var(--nova-surface) !important;
                border: 1px solid rgba(255, 255, 255, 0.1) !important;
                border-radius: 12px !important;
                color: var(--nova-text) !important;
                padding: 0.75rem !important;
            }
            
            .stTextInput > div > div:focus-within {
                border-color: var(--nova-secondary) !important;
                box-shadow: 0 0 0 2px rgba(0, 166, 255, 0.2) !important;
            }
            
            /* Tabs styling */
            .stTabs [data-baseweb="tab-list"] {
                background: var(--nova-surface);
                padding: 0.75rem;
                border-radius: 12px;
                border: 1px solid rgba(255, 255, 255, 0.1);
            }
            
            .stTabs [data-baseweb="tab"] {
                background: transparent;
                color: var(--nova-text);
                border-radius: 8px;
                margin: 0 0.25rem;
                padding: 0.75rem 1.5rem;
            }
            
            .stTabs [data-baseweb="tab"][aria-selected="true"] {
                background: linear-gradient(135deg, rgba(10, 37, 64, 0.95), rgba(0, 166, 255, 0.95));
                color: white;
            }
            
            /* Chat container styling */
            .chat-container {
                background: var(--nova-surface);
                border-radius: 15px;
                padding: 1.5rem;
                box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
                height: calc(100vh - 300px);
                overflow-y: auto;
                margin-bottom: 1rem;
                border: 1px solid rgba(255, 255, 255, 0.1);
            }
            
            /* Score card styling */
            .score-card {
                background: var(--nova-surface);
                padding: 2rem;
                border-radius: 15px;
                box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
                margin: 1.5rem 0;
                border: 1px solid rgba(255, 255, 255, 0.1);
            }
            
            .score-card h2 {
                color: var(--nova-text);
                margin-bottom: 1rem;
                font-size: 1.8rem;
                font-weight: 600;
                background: linear-gradient(to right, #fff, #E2E8F0);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
            }
            
            /* Metric styling */
            [data-testid="stMetricValue"] {
                background: linear-gradient(135deg, rgba(10, 37, 64, 0.95), rgba(0, 166, 255, 0.95));
                padding: 1.5rem;
                border-radius: 12px;
                color: white !important;
                font-size: 1.8rem !important;
                font-weight: 700 !important;
                text-align: center;
                border: 1px solid rgba(255, 255, 255, 0.1);
                box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
            }
            
            [data-testid="stMetricLabel"] {
                font-size: 1.1rem !important;
                font-weight: 500 !important;
                color: var(--nova-text) !important;
                margin-top: 0.75rem !important;
                text-transform: uppercase;
                letter-spacing: 0.5px;
            }
            
            /* Email display styling */
            .email-display {
                color: var(--nova-text);
                background: rgba(255, 255, 255, 0.1);
                padding: 0.5rem 1rem;
                border-radius: 8px;
                margin: 0.5rem 0;
                font-family: monospace;
            }
            </style>
        """, unsafe_allow_html=True)

        # Autenticazione rimossa temporaneamente - sarà implementata in una release futura
        # if not st.session_state.user:
        #     st.markdown("""
        #         <div class="main-header">
        #             <h1>Welcome to NOVA Crypto Analyzer</h1>
        #             <p>Please sign in with Google to access the application</p>
        #         </div>
        #     """, unsafe_allow_html=True)
        #     
        #     # Check for authentication code in URL
        #     if "code" in st.query_params:
        #         with st.spinner("Authenticating..."):
        #             user_info = auth_flow()
        #             if user_info:
        #                 st.session_state.user = user_info
        #                 st.session_state.authentication_state = "authenticated"
        #                 
        #                 # Clear URL parameters after successful authentication
        #                 is_local = os.environ.get('STREAMLIT_ENV', '') != 'production'
        #                 if is_local:
        #                     st.query_params.clear()
        #                     
        #                 st.rerun()
        #             else:
        #                 st.session_state.authentication_state = "failed"
        #                 
        #                 # Clear URL parameters after failed authentication
        #                 is_local = os.environ.get('STREAMLIT_ENV', '') != 'production'
        #                 if is_local:
        #                     st.query_params.clear()
        #     else:
        #         # Show login button
        #         auth_flow()
        #         
        #         # Show error message if authentication failed
        #         if st.session_state.authentication_state == "failed":
        #             st.error("Authentication failed. Please try again.")
        #             # Reset authentication state
        #             st.session_state.authentication_state = None
        #     return

        # Mostra l'app senza richiedere autenticazione
        with st.sidebar:
            try:
                # Try with use_container_width parameter (newer Streamlit versions)
                st.image("assets/Logo Asteroid Gray.jpeg", use_container_width=True)
            except TypeError:
                # Fallback for older Streamlit versions that don't support use_container_width
                st.image("assets/Logo Asteroid Gray.jpeg", width=None)
            st.markdown("""
                <div style='margin-bottom: 2rem;'>
                    <h2 style='color: white; font-size: 1.5rem; margin-bottom: 1rem;'>Navigation</h2>
                </div>
            """, unsafe_allow_html=True)
            page = st.radio("Navigation", ["Whitepaper Analyzer", "Whitepaper Scraper"], label_visibility="collapsed")
            
            # Nota informativa sull'accesso temporaneo senza login
            st.markdown(f"""
                <div style='padding: 1rem; background: rgba(255,255,255,0.1); border-radius: 10px; margin-top: 2rem;'>
                    <p style='color: #E0E0E0; margin-bottom: 0.5rem;'>Accesso temporaneo:</p>
                    <p style='color: white; font-weight: 500;'>Login disabilitato temporaneamente</p>
                    <p style='color: #E0E0E0; font-size: 0.8rem;'>Il sistema di autenticazione sarà implementato in una release futura</p>
                </div>
            """, unsafe_allow_html=True)

        if page == "Whitepaper Analyzer":
            st.markdown("""
                <div class="main-header">
                    <h1>Crypto Whitepaper Analyzer</h1>
                    <p>Upload a PDF whitepaper for comprehensive analysis</p>
                </div>
            """, unsafe_allow_html=True)
            
            # Show usage limits
            st.info(f"Usage limits: {st.session_state.analysis_count}/{MAX_ANALYSES} analyses used today")
            
            # Check if user has reached the limit
            if st.session_state.analysis_count >= MAX_ANALYSES:
                st.warning("You've reached your daily analysis limit. Please try again tomorrow.")
                
                # Show stored analyses
                st.subheader("Your Saved Analyses")
                stored_analyses = load_stored_analyses()
                
                if stored_analyses:
                    for i, analysis in enumerate(stored_analyses):
                        with st.expander(f"{analysis['project_name']} - {analysis['timestamp']}"):
                            st.json(analysis['data'])
                else:
                    st.write("No saved analyses found.")
                
                return
            
            # Main content area
            col1, col2 = st.columns([2, 1])

            with col1:
                uploaded_file = st.file_uploader("Choose a PDF file", type="pdf")
                if uploaded_file is not None:
                    # Extract text from PDF
                    whitepaper_text = extract_text_from_pdf(uploaded_file)
                    st.session_state.whitepaper_text = whitepaper_text
                    
                    # Optional: Display first few lines of extracted text
                    with st.expander("View extracted text preview"):
                        st.text(f"First 500 characters:\n{whitepaper_text[:500]}...")
            
                    # Attempt to extract project name
                    project_name = extract_project_name(whitepaper_text)
                    st.markdown(f"""
                        <div class="score-card">
                            <h2>Project Analysis: {project_name}</h2>
                        </div>
                    """, unsafe_allow_html=True)
            
                    # Perform analysis
                    with st.spinner("Analyzing Whitepaper..."):
                        # Increment the analysis counter
                        st.session_state.analysis_count += 1
                        
                        # Create tabs for different analyses
                        tab1, tab2, tab3, tab4 = st.tabs(["Tokenomics", "Technology", "Market", "Team"])
                        
                        with tab1:
                            tokenomics_analysis, tokenomics_score = analyze_with_perplexity(whitepaper_text, "tokenomics", max_points=30)
                            st.metric("Tokenomics Score", f"{tokenomics_score}/30")
                            st.write(tokenomics_analysis)
                        
                        with tab2:
                            tech_analysis, tech_score = analyze_with_perplexity(whitepaper_text, "technology", max_points=30)
                            st.metric("Technology Score", f"{tech_score}/30")
                            st.write(tech_analysis)
                        
                        with tab3:
                            market_analysis, market_score = analyze_with_perplexity(whitepaper_text, "market potential", max_points=20)
                            st.metric("Market Potential Score", f"{market_score}/20")
                            st.write(market_analysis)
                        
                        with tab4:
                            team_analysis, team_score = analyze_with_perplexity(whitepaper_text, "team", max_points=20)
                            st.metric("Team Score", f"{team_score}/20")
                            st.write(team_analysis)
                        
                        # Total Score
                        total_score = tokenomics_score + tech_score + market_score + team_score
                        st.markdown(f"""
                            <div class="score-card">
                                <h2>Total Project Score: {total_score}/100</h2>
                            </div>
                        """, unsafe_allow_html=True)
                        
                        # Additional Market Data in expandable sections
                        with st.expander("CoinMarketCap Data"):
                            coinmarketcap_data = analyze_coinmarketcap_data(project_name)
                            st.write(coinmarketcap_data)
                        
                        with st.expander("Reddit Sentiment"):
                            reddit_sentiment = analyze_reddit_sentiment(project_name)
                            st.write(reddit_sentiment)
                        
                        with st.expander("Market Sentiment"):
                            market_sentiment = analyze_market_sentiment(project_name)
                            st.write(market_sentiment)
                        
                        # Prepare the data for local storage
                        analysis_data = {
                            "project_name": project_name,
                            "total_score": total_score,
                            "tokenomics": {
                                "score": tokenomics_score,
                                "analysis": tokenomics_analysis
                            },
                            "technology": {
                                "score": tech_score,
                                "analysis": tech_analysis
                            },
                            "market": {
                                "score": market_score,
                                "analysis": market_analysis
                            },
                            "team": {
                                "score": team_score,
                                "analysis": team_analysis
                            },
                            "additional_data": {
                                "coinmarketcap": coinmarketcap_data,
                                "reddit": reddit_sentiment,
                                "market_sentiment": market_sentiment
                            }
                        }
                        
                        # Save analysis locally
                        save_analysis_locally(project_name, analysis_data)
                        
                        # Button for saving to GCS
                        col_cloud, col_local = st.columns(2)
                        
                        with col_cloud:
                            if st.button("Save Analysis to Cloud"):
                                with st.spinner("Generating and uploading analysis report..."):
                                    # Generate PDF report
                                    pdf_report = generate_analysis_pdf(
                                        project_name, 
                                        whitepaper_text, 
                                        tokenomics_analysis, 
                                        tokenomics_score, 
                                        tech_analysis, 
                                        tech_score, 
                                        market_analysis, 
                                        market_score, 
                                        team_analysis, 
                                        team_score, 
                                        total_score, 
                                        coinmarketcap_data, 
                                        reddit_sentiment, 
                                        market_sentiment
                                    )
                                    
                                    if pdf_report:
                                        # Upload to GCS
                                        gcs_url = upload_to_gcs(pdf_report, project_name)
                                        
                                        if gcs_url:
                                            st.success(f"Analysis report saved successfully!")
                                            
                                            # Also offer local download option
                                            pdf_report.seek(0)  # Reset buffer position
                                            st.download_button(
                                                "Download Analysis Report",
                                                pdf_report,
                                                f"{project_name}_analysis.pdf",
                                                "application/pdf"
                                            )
                                        else:
                                            st.error("Failed to upload report to cloud storage.")
                                    else:
                                        st.error("Failed to generate PDF report.")
                        
                        with col_local:
                            st.success("Analysis complete!")
                            st.info("Your report is ready to view.")

            # Chat interface in the sidebar
            with col2:
                st.markdown("""
                    <div style='background: white; padding: 1rem; border-radius: 10px; margin-bottom: 1rem;'>
                        <h2 style='color: var(--nova-primary); margin: 0;'>Whitepaper Chat</h2>
                    </div>
                """, unsafe_allow_html=True)
                
                # Create a container for chat messages
                chat_container = st.container()
                with chat_container:
                    st.markdown('<div class="chat-container">', unsafe_allow_html=True)
            for message in st.session_state.messages:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])
                    st.markdown('</div>', unsafe_allow_html=True)
            
                # Input box at the bottom
                if prompt := st.chat_input("Ask about the whitepaper"):
                    st.session_state.messages.append({"role": "user", "content": prompt})
                    
                    if st.session_state.whitepaper_text:
                        response = chat_with_perplexity(prompt, st.session_state.whitepaper_text)
                        st.session_state.messages.append({"role": "assistant", "content": response})
                    else:
                        st.warning("Please upload a whitepaper first.")

        else:  # Whitepaper Scraper page
            st.markdown("""
                <div class="main-header">
                    <h1>Whitepaper Scraper</h1>
                    <p>Enter a GitBook URL or direct PDF link to extract the whitepaper</p>
                </div>
            """, unsafe_allow_html=True)
            
            # Show usage limits
            st.info(f"Usage limits: {st.session_state.scrape_count}/{MAX_SCRAPES} scrapes used today")
            
            # Check if user has reached the limit
            if st.session_state.scrape_count >= MAX_SCRAPES:
                st.warning("You've reached your daily scraping limit. Please try again tomorrow.")
                
                # Show stored scrapes
                st.subheader("Your Saved Scrapes")
                stored_scrapes = load_stored_scrapes()
                
                if stored_scrapes:
                    for i, scrape in enumerate(stored_scrapes):
                        with st.expander(f"Scrape from {scrape['url']} - {scrape['timestamp']}"):
                            st.write(f"URL: {scrape['url']}")
                            st.write(f"Scraped on: {scrape['timestamp']}")
                else:
                    st.write("No saved scrapes found.")
                
                return
            
            url = st.text_input("Enter GitBook URL or direct PDF link:")
            
            if url:
                with st.spinner("Analyzing URL..."):
                    if is_pdf_url(url):
                        st.info("Direct PDF link detected. Downloading...")
                        pdf_content = download_pdf(url)
                        if pdf_content:
                            # Increment the scrape counter
                            st.session_state.scrape_count += 1
                            
                            st.success("PDF downloaded successfully!")
                            
                            # Get base64 for storage
                            base64_pdf = get_pdf_as_base64(pdf_content)
                            
                            # Save scrape locally
                            save_scrape_locally(url, base64_pdf)
                            
                            # Reset buffer for download
                            pdf_content.seek(0)
                            st.download_button(
                                "Download PDF",
                                pdf_content,
                                "whitepaper.pdf",
                                "application/pdf"
                            )
                            
                            # Extract text for analysis
                            pdf_content.seek(0)  # Reset buffer position
                            pdf_reader = PyPDF2.PdfReader(pdf_content)
                            text = ""
                            for page in pdf_reader.pages:
                                text += page.extract_text()
                            st.session_state.whitepaper_text = text
                    
                    elif is_gitbook_url(url):
                        st.info("GitBook detected. Scraping content...")
                        content = scrape_gitbook(url)
                        if content:
                            # Increment the scrape counter
                            st.session_state.scrape_count += 1
                            
                            st.success("Content scraped successfully!")
                            
                            # Create PDF
                            pdf_content = create_pdf_from_content(content)
                            if pdf_content:
                                # Get base64 for storage
                                base64_pdf = get_pdf_as_base64(pdf_content)
                                
                                # Save scrape locally
                                save_scrape_locally(url, base64_pdf)
                                
                                # Reset buffer for download
                                pdf_content.seek(0)
                                st.download_button(
                                    "Download PDF",
                                    pdf_content,
                                    "whitepaper.pdf",
                                    "application/pdf"
                                )
                                
                                # Extract text for analysis
                                pdf_content.seek(0)  # Reset buffer position
                                pdf_reader = PyPDF2.PdfReader(pdf_content)
                                text = ""
                                for page in pdf_reader.pages:
                                    text += page.extract_text()
                                st.session_state.whitepaper_text = text
                                
                                # Show preview
                                with st.expander("View scraped content"):
                                    for page in content:
                                        st.subheader(page['title'])
                                        st.write(page['content'])
                    
            else:
                        st.error("URL is neither a GitBook nor a direct PDF link. Please check the URL.")

            # Add tab for viewing saved scrapes
            if st.checkbox("View Saved Scrapes", key="view_scrapes_checkbox", label_visibility="visible"):
                st.subheader("Your Saved Scrapes")
                stored_scrapes = load_stored_scrapes()
                
                if stored_scrapes:
                    for i, scrape in enumerate(stored_scrapes):
                        with st.expander(f"Scrape from {scrape['url']} - {scrape['timestamp']}"):
                            st.write(f"URL: {scrape['url']}")
                            st.write(f"Scraped on: {scrape['timestamp']}")
                else:
                    st.write("No saved scrapes found.")

        # Add a sidebar element for viewing saved analyses
        with st.sidebar:
            if st.checkbox("View Saved Analyses", key="view_analyses_checkbox", label_visibility="visible"):
                st.subheader("Your Saved Analyses")
                stored_analyses = load_stored_analyses()
                
                if stored_analyses:
                    for i, analysis in enumerate(stored_analyses):
                        with st.expander(f"{analysis['project_name']} - {analysis['timestamp']}"):
                            st.write(f"Project: {analysis['project_name']}")
                            st.write(f"Total Score: {analysis['data']['total_score']}/100")
                            st.write(f"Analyzed on: {analysis['timestamp']}")
                else:
                    st.write("No saved analyses found.")
            
            # Add reset button for testing/admin
            if st.checkbox("Show Admin", key="show_admin_checkbox", label_visibility="visible"):
                if st.button("Reset Usage Counters"):
                    reset_usage_counts()
                    st.success("Usage counters reset!")
                    st.rerun()

    except Exception as e:
        st.error(f"An error occurred: {str(e)}")
    finally:
        # Clean up any remaining temporary files
        cleanup_temp_files()

if __name__ == "__main__":
    main()