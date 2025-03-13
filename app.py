import streamlit as st
import os
from dotenv import load_dotenv
import PyPDF2
import requests
import json
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import re
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
from reportlab.lib.units import inch
import tempfile
from pathlib import Path
import io
import firebase_admin
from firebase_admin import credentials, firestore
import time

# Load environment variables
load_dotenv()

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

# Determine if running locally or in production
is_local = os.environ.get('STREAMLIT_ENV', '') != 'production'
if is_local:
    # For local development
    REDIRECT_URI = "http://localhost:8501/"
else:
    # For production deployment
    REDIRECT_URI = "https://crypto-project-analyzer.streamlit.app/_oauth/google"
    
# Set environment variables
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1' 
PERPLEXITY_API_KEY = os.getenv('PERPLEXITY_API_KEY')

# Set Google Application Credentials
os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = os.path.join(os.path.dirname(__file__), 'nova-gcp-infra-d3488d86e9fa.json')

# Initialize Firebase Admin SDK
cred = credentials.Certificate('nova-gcp-infra-d3488d86e9fa.json')
try:
    app = firebase_admin.initialize_app(cred, {
        'projectId': 'nova-gcp-infra'
    })
except ValueError:
    app = firebase_admin.get_app()

# Initialize Firestore client
db = firestore.Client(project='nova-gcp-infra', database='cryptoanalysisappusersdb')

def check_user_access(email):
    """Check if user's email exists in the Firestore database."""
    try:
        # Debug information
        st.write(f"Checking access for email: {email}")
        
        # Query the users collection for the email
        users_ref = db.collection('Users')
        user_query = users_ref.where('email', '==', email).limit(1).get()
        
        # Print the query results for debugging
        results = list(user_query)
        
        has_access = len(results) > 0
        if not has_access:
            st.warning(f"User {email} not registered to the system.")
        else:
            st.success(f"Access granted for {email}")
        return has_access
    except Exception as e:
        st.error(f"Error checking user access: {str(e)}")
        st.error(f"Current working directory: {os.getcwd()}")
        st.error(f"Service account path: {os.environ.get('GOOGLE_APPLICATION_CREDENTIALS')}")
        return False

if not PERPLEXITY_API_KEY:
    st.error("Please set your PERPLEXITY_API_KEY in the .env file")
    st.stop()

# Initialize session state
if 'user' not in st.session_state:
    st.session_state.user = None

if 'messages' not in st.session_state:
    st.session_state.messages = []

if 'whitepaper_text' not in st.session_state:
    st.session_state.whitepaper_text = ""

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

def is_pdf_url(url):
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

def auth_flow():
    try:
        # Determine if running locally or in production
        is_local = os.environ.get('STREAMLIT_ENV', '') != 'production'
        
        # Create flow instance
        flow = Flow.from_client_secrets_file(
            'client_secret_487298376198-140i5gfel69hkaue4jqn27kjgo3s74k1.apps.googleusercontent.com.json',
            scopes=['openid', 'https://www.googleapis.com/auth/userinfo.profile', 'https://www.googleapis.com/auth/userinfo.email'],
            redirect_uri=REDIRECT_URI
        )

        # Get authorization code from URL parameters
        auth_code = st.query_params.get("code")
        
        if not auth_code:
            # Generate authorization URL
            auth_url, state = flow.authorization_url(
                access_type='offline',
                include_granted_scopes='true',
                prompt='consent'  # Force consent screen
            )
            st.markdown(f'[Login with Google]({auth_url})')
            return None

        # Exchange auth code for credentials
        try:
            flow.fetch_token(code=auth_code)
            credentials = flow.credentials

            # Get user info using credentials
            service = build('oauth2', 'v2', credentials=credentials)
            user_info = service.userinfo().get().execute()

            # Check if user exists in allowed_emails.txt
            with open('allowed_emails.txt', 'r') as f:
                allowed_emails = [email.strip() for email in f.readlines()]
            
            if user_info['email'] not in allowed_emails:
                st.error("Access denied. Your email is not authorized to use this application.")
                return None
                
            # Clear the URL parameters after successful authentication
            if is_local:
                # Use the new API to clear query parameters
                st.query_params.clear()
                
            return user_info
        except Exception as e:
            st.error(f"Error during authentication: {str(e)}")
            # Clear URL parameters to allow retrying
            if is_local:
                # Use the new API to clear query parameters
                st.query_params.clear()
            return None

    except Exception as e:
        st.error(f"Error in auth flow: {str(e)}")
        return None

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
    payload = {"model": "llama-3.1-sonar-small-128k-online", "messages": messages, "temperature": 0.2}
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
        "model": "llama-3.1-sonar-small-128k-online",
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
    payload = {"model": "llama-3.1-sonar-small-128k-online", "messages": messages, "temperature": 0.3}
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
    payload = {"model": "llama-3.1-sonar-small-128k-online", "messages": messages, "temperature": 0.3}
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
    payload = {"model": "llama-3.1-sonar-small-128k-online", "messages": messages, "temperature": 0.7}
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
    payload = {"model": "llama-3.1-sonar-small-128k-online", "messages": messages, "temperature": 0.1}
    headers = {"Authorization": f"Bearer {PERPLEXITY_API_KEY}", "Content-Type": "application/json"}
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.json()['choices'][0]['message']['content'].strip()
    except Exception as e:
        return None

def main():
    try:
        # Initialize session state for authentication
        if 'authentication_state' not in st.session_state:
            st.session_state.authentication_state = None
        if 'user' not in st.session_state:
            st.session_state.user = None
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

        # Authentication flow
        if not st.session_state.user:
            st.markdown("""
                <div class="main-header">
                    <h1>Welcome to NOVA Crypto Analyzer</h1>
                    <p>Please sign in with Google to access the application</p>
                </div>
            """, unsafe_allow_html=True)
            
            # Check for authentication code in URL
            if "code" in st.query_params:
                with st.spinner("Authenticating..."):
                    user_info = auth_flow()
                    if user_info:
                        st.session_state.user = user_info
                        st.session_state.authentication_state = "authenticated"
                        
                        # Clear URL parameters after successful authentication
                        is_local = os.environ.get('STREAMLIT_ENV', '') != 'production'
                        if is_local:
                            st.query_params.clear()
                            
                        st.rerun()
                    else:
                        st.session_state.authentication_state = "failed"
                        
                        # Clear URL parameters after failed authentication
                        is_local = os.environ.get('STREAMLIT_ENV', '') != 'production'
                        if is_local:
                            st.query_params.clear()
            else:
                # Show login button
                auth_flow()
                
                # Show error message if authentication failed
                if st.session_state.authentication_state == "failed":
                    st.error("Authentication failed. Please try again.")
                    # Reset authentication state
                    st.session_state.authentication_state = None
            return

        # Only show the rest of the app if user is authenticated
        with st.sidebar:
            st.image("https://placehold.co/200x80?text=NOVA+Logo", use_column_width=True)
            st.markdown("""
                <div style='margin-bottom: 2rem;'>
                    <h2 style='color: white; font-size: 1.5rem; margin-bottom: 1rem;'>Navigation</h2>
                </div>
            """, unsafe_allow_html=True)
            page = st.radio("", ["Whitepaper Analyzer", "Whitepaper Scraper"])
            
            st.markdown(f"""
                <div style='padding: 1rem; background: rgba(255,255,255,0.1); border-radius: 10px; margin-top: 2rem;'>
                    <p style='color: #E0E0E0; margin-bottom: 0.5rem;'>Logged in as:</p>
                    <p style='color: white; font-weight: 500;'>{st.session_state.user['email']}</p>
                </div>
            """, unsafe_allow_html=True)
            if st.button("Logout"):
                st.session_state.user = None
                st.experimental_rerun()

        if page == "Whitepaper Analyzer":
            st.markdown("""
                <div class="main-header">
                    <h1>Crypto Whitepaper Analyzer</h1>
                    <p>Upload a PDF whitepaper for comprehensive analysis</p>
                </div>
            """, unsafe_allow_html=True)
            
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
            
            url = st.text_input("Enter GitBook URL or direct PDF link:")
            
            if url:
                with st.spinner("Analyzing URL..."):
                    if is_pdf_url(url):
                        st.info("Direct PDF link detected. Downloading...")
                        pdf_content = download_pdf(url)
                        if pdf_content:
                            st.success("PDF downloaded successfully!")
                            st.download_button(
                                "Download PDF",
                                pdf_content,
                                "whitepaper.pdf",
                                "application/pdf"
                            )
                            # Extract text for analysis
                            pdf_reader = PyPDF2.PdfReader(pdf_content)
                            text = ""
                            for page in pdf_reader.pages:
                                text += page.extract_text()
                            st.session_state.whitepaper_text = text
                    
                    elif is_gitbook_url(url):
                        st.info("GitBook detected. Scraping content...")
                        content = scrape_gitbook(url)
                        if content:
                            st.success("Content scraped successfully!")
                            
                            # Create PDF
                            pdf_content = create_pdf_from_content(content)
                            if pdf_content:
                                st.download_button(
                                    "Download PDF",
                                    pdf_content,
                                    "whitepaper.pdf",
                                    "application/pdf"
                                )
                                
                                # Extract text for analysis
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

    except Exception as e:
        st.error(f"An error occurred: {str(e)}")
    finally:
        # Clean up any remaining temporary files
        cleanup_temp_files()

if __name__ == "__main__":
    main()