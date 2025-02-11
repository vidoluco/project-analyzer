def create_pdf_from_content(content):
    """Create PDF from scraped content using reportlab."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import letter
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
        from reportlab.lib.units import inch
        from io import BytesIO
        import requests
        
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
        
        # Container for the 'Flowable' objects
        elements = []
        
        # Get styles
        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(
            name='CustomTitle',
            parent=styles['Heading1'],
            fontSize=24,
            spaceAfter=30
        ))
        
        for page in content:
            # Add title
            if page.get('title'):
                elements.append(Paragraph(page['title'], styles['CustomTitle']))
            
            # Add images
            if 'images' in page and page['images']:
                for img in page['images']:
                    try:
                        # Download image
                        response = requests.get(img['src'])
                        if response.status_code == 200:
                            img_buffer = BytesIO(response.content)
                            img_element = Image(img_buffer, width=6*inch, height=4*inch, kind='proportional')
                            elements.append(img_element)
                            elements.append(Spacer(1, 12))
                    except Exception as img_error:
                        st.warning(f"Could not load image: {str(img_error)}")
            
            # Add content
            content_paragraphs = page['content'].split('\n')
            for paragraph in content_paragraphs:
                if paragraph.strip():
                    elements.append(Paragraph(paragraph, styles['Normal']))
                    elements.append(Spacer(1, 12))
            
            # Add page break
            elements.append(Spacer(1, 50))
        
        # Build PDF
        doc.build(elements)
        
        # Get the value of the BytesIO buffer
        pdf = buffer.getvalue()
        buffer.close()
        
        return BytesIO(pdf)
    except Exception as e:
        st.error(f"Error creating PDF: {str(e)}")
        return None 