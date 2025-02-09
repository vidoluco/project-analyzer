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
import pdfkit
import tempfile
from pathlib import Path
import io
import firebase_admin
from firebase_admin import credentials, firestore

load_dotenv()
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1' 
PERPLEXITY_API_KEY = os.getenv('PERPLEXITY_API_KEY')
REDIRECT_URI = "http://localhost:8501/"

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
        if 'application/pdf' in response.headers.get('content-type', '').lower():
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
            'a[href$=".pdf"]'
        ]
        
        for indicator in pdf_indicators:
            elements = soup.select(indicator)
            if elements:
                # Try to extract PDF URL from viewer
                for element in elements:
                    pdf_url = element.get('src') or element.get('href')
                    if pdf_url and pdf_url.lower().endswith('.pdf'):
                        return pdf_url
        
        # Check for PDF in page content
        pdf_links = soup.select('a[href$=".pdf"]')
        if pdf_links:
            return urljoin(url, pdf_links[0]['href'])
            
        return False
    except:
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
            '.page-inner',  # Classic GitBook
            'article',  # Generic article
            '.markdown-section',  # Modern GitBook
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
            for element in content.select('.js-toc-content, .js-toc, nav, header, footer, .toolbar-button'):
                element.decompose()
            
            # Get title from various possible locations
            title = None
            title_selectors = [
                'h1:first-of-type',
                '.page-title',
                '.header-title',
                'title'
            ]
            
            for selector in title_selectors:
                title_elem = soup.select_one(selector)
                if title_elem:
                    title = title_elem.get_text(strip=True)
                    break
            
            return {
                'title': title or soup.title.string if soup.title else '',
                'content': content.get_text(separator='\n', strip=True)
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
        # Try different menu selectors for various GitBook versions
        menu_selectors = [
            '.summary',  # Classic GitBook
            '.book-summary',  # Alternative GitBook
            'nav',  # Generic navigation
            '.reset-3c756112--menuContainer-6683485e',  # Modern GitBook
            '.book-menu',  # Common menu class
            '.sidebar-nav',  # Common sidebar navigation
            '.table-of-contents'  # Generic ToC
        ]
        
        menu = None
        for selector in menu_selectors:
            menu = soup.select_one(selector)
            if menu:
                break
        
        if menu:
            # Get all links from menu
            for link in menu.select('a[href]'):
                href = link.get('href')
                if href and not href.startswith(('#', 'javascript:', 'mailto:')):
                    # Clean up the URL
                    if href.startswith('//'):
                        href = 'https:' + href
                    elif href.startswith('/'):
                        href = urljoin(url, href)
                    else:
                        href = urljoin(url, href)
                    
                    menu_items.append({
                        'title': link.get_text(strip=True),
                        'url': href
                    })
        
        # If no menu found, try to find links in the main content
        if not menu_items:
            content_links = soup.select('main a[href], .content a[href], article a[href]')
            for link in content_links:
                href = link.get('href')
                if href and not href.startswith(('#', 'javascript:', 'mailto:')):
                    href = urljoin(url, href)
                    menu_items.append({
                        'title': link.get_text(strip=True),
                        'url': href
                    })
        
        return menu_items
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
        for i, item in enumerate(menu_items):
            # Update progress
            current_progress = (i + 1) / total_items
            progress_bar.progress(current_progress, text=f"Scraping: {item['title']} ({i+1}/{total_items})")
            
            # Scrape the page
            page_content = scrape_gitbook_page(item['url'])
            if page_content:
                content.append(page_content)
                st.success(f"✓ {item['title']}")
            else:
                st.warning(f"⚠️ Failed to scrape: {item['title']}")
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
    """Create PDF from scraped content."""
    try:
        # Create temporary HTML file
        with tempfile.NamedTemporaryFile(suffix='.html', delete=False, mode='w', encoding='utf-8') as f:
            html_content = "<html><body>"
            for page in content:
                html_content += f"<h1>{page['title']}</h1>{page['content']}<hr>"
            html_content += "</body></html>"
            f.write(html_content)
            temp_html = f.name

        # Convert HTML to PDF
        pdf_output = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
        pdfkit.from_file(temp_html, pdf_output.name)
        
        # Read the PDF content
        with open(pdf_output.name, 'rb') as f:
            pdf_content = io.BytesIO(f.read())
        
        # Cleanup temporary files
        os.unlink(temp_html)
        os.unlink(pdf_output.name)
        
        return pdf_content
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
        auth_url, _ = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true'
        )
        st.markdown(f'[Login with Google]({auth_url})')
        return None

    try:
        # Exchange auth code for credentials
        flow.fetch_token(code=auth_code)
        credentials = flow.credentials

        # Get user info using credentials
        service = build('oauth2', 'v2', credentials=credentials)
        user_info = service.userinfo().get().execute()

        # Check if user exists in Firestore
        if not check_user_access(user_info['email']):
            st.error("Access denied. Your email is not authorized to use this application. Contact the administrator.")
            return None

        return user_info
    except Exception as e:
        st.error(f"Authentication failed: {str(e)}")
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
    st.title("Crypto Project Analyzer")
    
    # Check if user is authenticated
    if not st.session_state.user:
        st.write("Please sign in with Google to access the application")
        user_info = auth_flow()
        if user_info:
            st.session_state.user = user_info
            st.rerun()
        return

    # Only show the rest of the app if user is authenticated
    with st.sidebar:
        st.title("Navigation")
        page = st.radio("Go to", ["Whitepaper Analyzer", "Whitepaper Scraper"])
        
        st.write(f"Logged in as: {st.session_state.user['email']}")
        if st.button("Logout"):
            st.session_state.user = None
            st.experimental_rerun()

    if page == "Whitepaper Analyzer":
        st.title("Crypto Whitepaper Analyzer")
        
        # Main content area
        col1, col2 = st.columns([2, 1])

        with col1:
            st.write("Upload a PDF whitepaper for comprehensive analysis")
            
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
                st.write(f"Detected Project: {project_name}")
                
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
                    st.header(f"Total Project Score: {total_score}/100")
                    
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
            st.subheader("Whitepaper Chat")
            
            # Create a container for chat messages with custom height
            chat_container = st.container()
            
            # Add some spacing
            st.write("")
            
            # Input box at the bottom
            if prompt := st.chat_input("Ask about the whitepaper"):
                st.session_state.messages.append({"role": "user", "content": prompt})
                
                if st.session_state.whitepaper_text:
                    response = chat_with_perplexity(prompt, st.session_state.whitepaper_text)
                    st.session_state.messages.append({"role": "assistant", "content": response})
                else:
                    st.warning("Please upload a whitepaper first.")
            
            # Display messages in the container
            with chat_container:
                for message in st.session_state.messages:
                    with st.chat_message(message["role"]):
                        st.markdown(message["content"])

    else:  # Whitepaper Scraper page
        st.title("Whitepaper Scraper")
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

if __name__ == "__main__":
    main()