# Crypto Project Analyzer

A powerful tool for analyzing cryptocurrency project whitepapers using AI to provide comprehensive scoring and insights.

## Features

- **Whitepaper Analysis**: Upload PDF whitepapers for detailed analysis
- **Website Scraping**: Extract whitepaper content from GitBook and other sources
- **AI-Powered Analysis**: Get scoring on tokenomics, technology, market potential, and team
- **Cloud Storage**: Save analysis reports to Google Cloud Storage
- **Usage Management**: Daily limits of 7 analyses and 15 scrapes
- **Interactive Chat**: Ask questions about the whitepaper and get AI-powered answers

## Setup

### Prerequisites

- Python 3.8+
- Google Cloud Platform account (for cloud storage)
- Perplexity API key

### Installation

1. Clone the repository
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Copy the `.env.template` file to `.env` and add your API keys:
   ```
   cp .env.template .env
   ```

### Setting up Google Cloud Storage

1. Create a Google Cloud Platform account if you don't have one
2. Create a new project in the GCP Console
3. Enable the Cloud Storage API for your project
4. Create a storage bucket named `crypto-analysis-storage` (or choose your own name)
5. Create a service account with Storage Admin permissions
6. Download the service account key JSON file
7. Update your `.env` file with the bucket name and path to credentials:
   ```
   GCS_BUCKET_NAME=crypto-analysis-storage/analysis_outputs
   GOOGLE_APPLICATION_CREDENTIALS=./path/to/credentials.json
   ```

## Usage

Run the application:
```
streamlit run app.py
```

### Analyzing a Whitepaper

1. Upload a PDF whitepaper
2. The app will analyze the whitepaper and provide scoring across multiple dimensions
3. Click "Save Analysis to Cloud" to store the report in your GCS bucket
4. Use the chat interface to ask specific questions about the whitepaper

### Usage Limits

The application includes the following daily usage limits:
- **7 analyses** per day for the Whitepaper Analyzer
- **15 scrapes** per day for the Whitepaper Scraper

These limits help maintain performance and control API usage.

### Accessing Saved Reports in the Cloud

Reports are saved in your GCS bucket with the following naming format:
```
analysis_outputs/analysis_{project_name}_{timestamp}_{unique_id}.pdf
```

You can access them through:
- The GCP Console
- GCS-compatible tools and libraries

## License

[MIT License](LICENSE)

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request. 