import streamlit as st
import requests
from bs4 import BeautifulSoup
import os
from dotenv import load_dotenv
import json
from urllib.parse import urljoin, urlparse
import time
import re
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from io import BytesIO

# Load environment variables
load_dotenv()
PERPLEXITY_API_KEY = os.getenv('PERPLEXITY_API_KEY')

def is_valid_url(url):
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except:
        return False

def scrape_website(url):
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Cache-Control': 'max-age=0'
        }
        response = requests.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        
        # Save raw HTML
        timestamp = time.strftime("%Y%m%d-%H%M%S")
        filename = f"scraped_html_{timestamp}.html"
        with open(filename, "w", encoding="utf-8") as f:
            f.write(response.text)
        st.success(f"Raw HTML saved to {filename}")
        
        return response.text
    except Exception as e:
        st.error(f"Error scraping website: {str(e)}")
        return None

def extract_sections(html_content, base_url):
    soup = BeautifulSoup(html_content, 'html.parser')
    sections = {}
    
    # Common section identifiers with expanded patterns
    section_identifiers = {
        'about': ['about', 'overview', 'introduction', 'who-we-are', 'mission', 'vision'],
        'features': ['features', 'technology', 'solutions', 'product', 'services', 'what-we-do'],
        'team': ['team', 'about-us', 'our-team', 'people', 'leadership', 'founders'],
        'roadmap': ['roadmap', 'timeline', 'milestones', 'future', 'development'],
        'tokenomics': ['tokenomics', 'token', 'economics', 'tokeneconomics', 'distribution', 'supply'],
        'docs': ['docs', 'documentation', 'whitepaper', 'papers', 'resources', 'learn'],
        'community': ['community', 'social', 'ecosystem', 'network', 'partners']
    }
    
    # Extract main content sections
    for section_type, identifiers in section_identifiers.items():
        for identifier in identifiers:
            # Method 1: Direct class or ID match with expanded attributes
            elements = []
            for element in soup.find_all(class_=lambda x: x and any(id_str in x.lower() for id_str in identifiers)):
                elements.append(element)
            for element in soup.find_all(id=lambda x: x and any(id_str in x.lower() for id_str in identifiers)):
                elements.append(element)
            
            # Method 2: Section tags and common container elements
            for tag in ['section', 'div', 'article', 'main', 'aside']:
                for element in soup.find_all(tag):
                    # Check data attributes
                    for attr, value in element.attrs.items():
                        if isinstance(value, str) and any(id_str in value.lower() for id_str in identifiers):
                            elements.append(element)
                            break
                        elif isinstance(value, list) and any(any(id_str in str(v).lower() for id_str in identifiers) for v in value):
                            elements.append(element)
                            break
            
            # Method 3: Look for sections with matching headings
            for heading in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
                if any(id_str in heading.get_text().lower() for id_str in identifiers):
                    parent = heading.find_parent(['section', 'div', 'article'])
                    if parent:
                        elements.append(parent)
            
            # Method 4: Look for content in common layout patterns
            for element in soup.find_all(['main', 'article', 'div']):
                if element.get('role') in ['main', 'article', 'contentinfo']:
                    if any(id_str in element.get_text().lower() for id_str in identifiers):
                        elements.append(element)
            
            # Process found elements
            for element in elements:
                # Clean and normalize text
                text = element.get_text(separator=' ', strip=True)
                text = re.sub(r'\s+', ' ', text)  # Normalize whitespace
                text = re.sub(r'[^\x00-\x7F]+', '', text)  # Remove non-ASCII characters
                
                if len(text) > 50:  # Only include substantial content
                    key = f"{section_type}_{len(sections)}"
                    sections[key] = {
                        'text': text,
                        'html': str(element),
                        'type': section_type,
                        'identifier': identifier
                    }
    
    # Extract links with improved context
    links = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        text = a.get_text(strip=True)
        
        # Get better context
        context = ""
        parent = a.find_parent(['p', 'div', 'section', 'article'])
        if parent:
            context = parent.get_text(strip=True)
            # Limit context length and clean it
            context = re.sub(r'\s+', ' ', context)
            context = context[:200] + '...' if len(context) > 200 else context
        
        if href.startswith(('http', 'https')):
            full_url = href
        else:
            full_url = urljoin(base_url, href)
        
        # Only include links with meaningful text or context
        if text or context:
            links.append({
                'url': full_url,
                'text': text,
                'context': context
            })
    
    return sections, links

def analyze_content(content, section_name=""):
    url = "https://api.perplexity.ai/chat/completions"
    
    messages = [
        {"role": "system", "content": "You are an expert at analyzing cryptocurrency and blockchain project websites. Extract and analyze key information about the project."},
        {"role": "user", "content": f"Analyze this {section_name} content from the project website and extract key information about the project. Focus on technical details, features, team, roadmap, and any unique aspects: {content[:4000]}"}
    ]
    
    payload = {
        "model": "sonar-pro",
        "messages": messages,
        "temperature": 0.3
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
        return f"Error in analysis: {str(e)}"

def clean_html_for_pdf(html_content):
    # Create a new BeautifulSoup object to clean the HTML
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Remove problematic attributes
    for tag in soup.find_all(True):  # Find all tags
        # Keep only safe attributes
        allowed_attrs = ['href', 'src', 'alt']
        attrs = dict(tag.attrs)
        for attr in attrs:
            if attr not in allowed_attrs:
                del tag[attr]
    
    # Convert specific tags to more basic ones
    for tag in soup.find_all(['div', 'section', 'article', 'main', 'aside']):
        tag.name = 'p'
    
    # Remove style and script tags
    for tag in soup.find_all(['style', 'script']):
        tag.decompose()
    
    # Get text with basic HTML
    cleaned_html = str(soup)
    
    # Remove any remaining problematic characters
    cleaned_html = re.sub(r'[^\x00-\x7F]+', '', cleaned_html)
    
    return cleaned_html

def generate_analysis_report(data):
    # Create a BytesIO buffer to receive PDF data
    buffer = BytesIO()
    
    # Create the PDF document
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=72,
        leftMargin=72,
        topMargin=72,
        bottomMargin=72
    )
    
    # Get styles
    styles = getSampleStyleSheet()
    title_style = styles['Heading1']
    heading_style = styles['Heading2']
    normal_style = styles['Normal']
    
    # Create custom style for code sections
    code_style = ParagraphStyle(
        'CodeStyle',
        parent=styles['Normal'],
        fontName='Courier',
        fontSize=8,
        spaceAfter=10,
        wordWrap='CJK'  # Better handling of long strings
    )
    
    # Container for PDF elements
    elements = []
    
    # Title
    elements.append(Paragraph("Project Website Analysis Report", title_style))
    elements.append(Spacer(1, 12))
    
    # Basic Information
    elements.append(Paragraph("Basic Information", heading_style))
    elements.append(Paragraph(f"URL: {data['url']}", normal_style))
    elements.append(Paragraph(f"Analysis Date: {data['timestamp']}", normal_style))
    elements.append(Spacer(1, 12))
    
    # Sections Analysis
    elements.append(Paragraph("Content Sections", heading_style))
    elements.append(Spacer(1, 12))
    
    for section_name, content in data['sections'].items():
        # Section title
        elements.append(Paragraph(section_name.replace('_', ' ').title(), heading_style))
        
        # Extracted text
        elements.append(Paragraph("Extracted Text:", styles['Heading3']))
        elements.append(Paragraph(content['text'], normal_style))
        elements.append(Spacer(1, 12))
        
        # Clean and add HTML content
        try:
            cleaned_html = clean_html_for_pdf(content['html'])
            elements.append(Paragraph("Raw HTML:", styles['Heading3']))
            elements.append(Paragraph(cleaned_html, code_style))
        except Exception as e:
            elements.append(Paragraph(f"Error displaying HTML: {str(e)}", normal_style))
        elements.append(Spacer(1, 12))
        
        # Analysis
        if 'analysis' in data and section_name in data['analysis']:
            elements.append(Paragraph("Analysis:", styles['Heading3']))
            elements.append(Paragraph(data['analysis'][section_name], normal_style))
        
        elements.append(Spacer(1, 20))
    
    # Links Analysis
    elements.append(Paragraph("Extracted Links", heading_style))
    elements.append(Spacer(1, 12))
    
    # Create table for links
    link_data = []
    link_data.append(["URL", "Text", "Context"])  # Header row
    
    for link in data['links']:
        # Clean and truncate text for table cells
        url = link['url'][:100] + '...' if len(link['url']) > 100 else link['url']
        text = link['text'][:100] + '...' if len(link['text']) > 100 else link['text']
        context = link['context'][:200] + '...' if len(link['context']) > 200 else link['context']
        
        link_data.append([
            Paragraph(url, normal_style),
            Paragraph(text, normal_style),
            Paragraph(context, normal_style)
        ])
    
    if link_data:
        # Create table with links
        table = Table(link_data, colWidths=[2.5*inch, 2*inch, 3*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 14),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('TEXTCOLOR', (0, 1), (-1, -1), colors.black),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 10),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        elements.append(table)
    
    # Build PDF document
    try:
        doc.build(elements)
    except Exception as e:
        # If building fails, try a simpler version without HTML content
        elements = [
            Paragraph("Project Website Analysis Report", title_style),
            Spacer(1, 12),
            Paragraph(f"URL: {data['url']}", normal_style),
            Paragraph(f"Analysis Date: {data['timestamp']}", normal_style),
            Spacer(1, 12),
            Paragraph("Note: Some content was omitted due to formatting issues.", normal_style)
        ]
        doc.build(elements)
    
    # Get the value of the BytesIO buffer
    pdf_data = buffer.getvalue()
    buffer.close()
    
    return pdf_data

def main():
    st.title("Project Website Scraper")
    
    # URL input
    url = st.text_input("Enter project website URL")
    
    if url and st.button("Analyze Website"):
        if not is_valid_url(url):
            st.error("Please enter a valid URL")
            return
        
        with st.spinner("Scraping website content..."):
            html_content = scrape_website(url)
            if html_content:
                sections, links = extract_sections(html_content, url)
                
                # Store data in session state
                if 'scraped_data' not in st.session_state:
                    st.session_state.scraped_data = {}
                
                st.session_state.scraped_data = {
                    'url': url,
                    'sections': sections,
                    'links': links,
                    'html_content': html_content,
                    'timestamp': time.strftime("%Y%m%d-%H%M%S")
                }
                
                # Create tabs for different types of analysis
                content_tab, links_tab, analysis_tab, raw_tab = st.tabs(["Content", "Links", "Analysis", "Raw HTML"])
                
                with content_tab:
                    st.subheader("Extracted Content Sections")
                    if not sections:
                        st.warning("No sections were extracted. The website might be using JavaScript to load content dynamically.")
                    
                    for section_name, content in sections.items():
                        with st.expander(f"{section_name.replace('_', ' ').title()}"):
                            st.markdown("### Extracted Text")
                            st.write(content['text'])
                            st.markdown("### Raw HTML")
                            st.code(content['html'], language='html')
                
                with links_tab:
                    st.subheader("Found Links")
                    for link in links:
                        with st.expander(f"{link['text'] or link['url'][:50]}..."):
                            st.write(f"URL: {link['url']}")
                            st.write(f"Text: {link['text']}")
                            st.write(f"Context: {link['context']}")
                
                with analysis_tab:
                    st.subheader("Content Analysis")
                    
                    # Analyze each section
                    analysis_results = {}
                    for section_name, content in sections.items():
                        with st.spinner(f"Analyzing {section_name}..."):
                            analysis = analyze_content(content['text'], section_name)
                            analysis_results[section_name] = analysis
                            
                            with st.expander(f"{section_name.replace('_', ' ').title()} Analysis"):
                                st.write(analysis)
                    
                    # Store analysis results
                    st.session_state.scraped_data['analysis'] = analysis_results
                
                with raw_tab:
                    st.subheader("Raw HTML Content")
                    st.code(html_content[:10000] + "..." if len(html_content) > 10000 else html_content, language='html')
                    
                    if st.download_button(
                        label="Download Raw HTML",
                        data=html_content,
                        file_name=f"raw_html_{st.session_state.scraped_data['timestamp']}.html",
                        mime="text/html"
                    ):
                        st.success("Raw HTML downloaded successfully")
                
                # Download complete analysis button
                if st.download_button(
                    label="Download Complete Analysis",
                    data=generate_analysis_report(st.session_state.scraped_data),
                    file_name=f"project_analysis_{st.session_state.scraped_data['timestamp']}.pdf",
                    mime="application/pdf"
                ):
                    st.success("Complete analysis downloaded successfully")

if __name__ == "__main__":
    main() 