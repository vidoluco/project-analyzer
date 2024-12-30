import streamlit as st
import os
from dotenv import load_dotenv
import PyPDF2
import requests
import json
import re

# Load environment variables
load_dotenv()
PERPLEXITY_API_KEY = os.getenv('PERPLEXITY_API_KEY')

if not PERPLEXITY_API_KEY:
    st.error("Please set your PERPLEXITY_API_KEY in the .env file")
    st.stop()

# Initialize session state for chat
if 'messages' not in st.session_state:
    st.session_state.messages = []
if 'whitepaper_text' not in st.session_state:
    st.session_state.whitepaper_text = ""

def extract_text_from_pdf(pdf_file):
    pdf_reader = PyPDF2.PdfReader(pdf_file)
    text = ""
    for page in pdf_reader.pages:
        text += page.extract_text()
    return text

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
    
    payload = {
        "model": "llama-3.1-sonar-small-128k-online",
        "messages": messages,
        "temperature": 0.2
    }
    
    headers = {
        "Authorization": f"Bearer {PERPLEXITY_API_KEY}",
        "Content-Type": "application/json"
    }
    
    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        analysis = response.json()['choices'][0]['message']['content']
        score = extract_score_from_analysis(analysis, max_points)
        
        # If score is 0, try to append a request for explicit scoring
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
        {"role": "system", "content": "You are a cryptocurrency market data analyst. Search and analyze CoinMarketCap data for the specified project. Focus on key metrics, market performance, and trading data."},
        {"role": "user", "content": f"Search and analyze CoinMarketCap data for {project_name}. Include:\n1. Current price and market cap\n2. 24h volume and liquidity\n3. Price changes (24h, 7d, 30d)\n4. Market cap rank\n5. Trading pairs and exchanges\n6. Historical price trends\n7. Key metrics and indicators\nProvide specific numbers and data points where available."}
    ]
    
    payload = {
        "model": "llama-3.1-sonar-small-128k-online",
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
        return f"Error in CoinMarketCap analysis: {str(e)}"

def analyze_reddit_sentiment(project_name):
    url = "https://api.perplexity.ai/chat/completions"
    
    messages = [
        {"role": "system", "content": "You are a social media analyst specializing in cryptocurrency communities. Search and analyze Reddit discussions about the specified project. Focus on community sentiment, discussions, and trends."},
        {"role": "user", "content": f"Search and analyze Reddit discussions about {project_name}. Include:\n1. Main subreddit size and activity\n2. Recent popular discussions and topics\n3. Community sentiment analysis\n4. Common concerns or praise\n5. Developer engagement\n6. Project updates and announcements\n7. Community growth trends\nProvide specific numbers and examples where available."}
    ]
    
    payload = {
        "model": "llama-3.1-sonar-small-128k-online",
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
        return f"Error in Reddit analysis: {str(e)}"

def analyze_market_sentiment(project_name):
    url = "https://api.perplexity.ai/chat/completions"
    
    messages = [
        {"role": "system", "content": "You are a cryptocurrency market analyst. Provide a comprehensive but concise analysis of the project's market presence, community sentiment, and overall reputation. Focus on recent developments, community engagement, and market perception."},
        {"role": "user", "content": f"Research and analyze the current market sentiment, community engagement, and overall reputation of the {project_name} project. Consider:\n1. Social media presence and engagement (Twitter, Discord)\n2. Recent developments and announcements\n3. Community size and activity\n4. Market performance and trends\n5. Expert opinions and reviews\n6. Red flags or concerns\n7. Unique selling points\nProvide a balanced analysis with specific data points where available."}
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
        return f"Error in market analysis: {str(e)}"

def main():
    st.title("Whitepaper Analysis Tool")
    
    # Create two columns: main content and chat
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.write("Upload a PDF whitepaper for comprehensive analysis")
        project_name = st.text_input("Project Name", help="Enter the name of the project for market research")
        uploaded_file = st.file_uploader("Choose a PDF file", type="pdf")
        
        if uploaded_file:
            text = extract_text_from_pdf(uploaded_file)
            st.session_state.whitepaper_text = text  # Store the text in session state
            
            aspects = {
                "Technical Foundation": 25,
                "Team & Leadership": 20,
                "Tokenomics": 15,
                "Market & Adoption": 15,
                "Documentation & Communication": 10,
                "Risk Assessment": 15
            }
            
            total_score = 0
            analysis_results = {}
            
            with st.spinner("Analyzing whitepaper..."):
                for aspect, max_points in aspects.items():
                    st.subheader(f"{aspect} (Max {max_points} points)")
                    analysis, score = analyze_with_perplexity(text, aspect, max_points)
                    st.write(analysis)
                    st.write(f"Calculated Score: {score}/{max_points}")
                    
                    total_score += score
                    analysis_results[aspect] = {"score": score, "analysis": analysis}
            
            st.subheader("Final Score")
            st.write(f"Total Score: {round(total_score, 1)}/100")
            
            # Score interpretation
            if total_score >= 90:
                st.success("Excellent project with high potential")
            elif total_score >= 80:
                st.info("Strong project with good fundamentals")
            elif total_score >= 70:
                st.warning("Decent project with some concerns")
            elif total_score >= 60:
                st.warning("Risky project with significant issues")
            else:
                st.error("High-risk project, major red flags")
            
            # Market Research and Community Analysis
            if project_name:
                st.subheader("Market Research & Community Analysis")
                
                # Create tabs for different analyses
                market_tab, cmc_tab, reddit_tab = st.tabs(["General Market Analysis", "CoinMarketCap Data", "Reddit Analysis"])
                
                with market_tab:
                    with st.spinner("Analyzing general market sentiment..."):
                        market_analysis = analyze_market_sentiment(project_name)
                        st.write(market_analysis)
                
                with cmc_tab:
                    with st.spinner("Fetching CoinMarketCap data..."):
                        cmc_analysis = analyze_coinmarketcap_data(project_name)
                        st.write(cmc_analysis)
                
                with reddit_tab:
                    with st.spinner("Analyzing Reddit sentiment..."):
                        reddit_analysis = analyze_reddit_sentiment(project_name)
                        st.write(reddit_analysis)
                
                # Add research sources
                st.subheader("Data Sources")
                st.info("""
                The analysis is based on real-time data from:
                
                Market Data:
                - CoinMarketCap metrics and trading data
                - Market aggregators and price feeds
                - Trading volume and liquidity data
                
                Community Data:
                - Reddit communities and discussions
                - Twitter engagement metrics
                - Discord community activity
                - Telegram groups
                
                News and Analysis:
                - Cryptocurrency news outlets
                - Expert reviews and analysis
                - Technical analysis reports
                - Development updates
                """)
            else:
                st.info("Enter the project name above to get market research and community analysis.")
    
    with col2:
        st.sidebar.title("Chat with Analysis Assistant")
        
        # Only show chat if whitepaper is uploaded
        if st.session_state.whitepaper_text:
            # Display chat messages
            for message in st.session_state.messages:
                with st.chat_message(message["role"]):
                    st.write(message["content"])
            
            # Chat input
            user_message = st.chat_input("Ask a question about the whitepaper...")
            
            if user_message:
                # Add user message to chat history
                st.session_state.messages.append({"role": "user", "content": user_message})
                
                # Get AI response
                ai_response = chat_with_perplexity(user_message, st.session_state.whitepaper_text)
                
                # Add AI response to chat history
                st.session_state.messages.append({"role": "assistant", "content": ai_response})
                
                # Rerun to update chat display
                st.rerun()
        else:
            st.sidebar.info("Upload a whitepaper to start chatting about it.")

if __name__ == "__main__":
    main() 