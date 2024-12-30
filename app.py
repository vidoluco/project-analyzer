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

def main():
    st.title("Whitepaper Analysis Tool")
    st.write("Upload a PDF whitepaper for comprehensive analysis")
    
    uploaded_file = st.file_uploader("Choose a PDF file", type="pdf")
    
    if uploaded_file:
        text = extract_text_from_pdf(uploaded_file)
        
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

if __name__ == "__main__":
    main() 