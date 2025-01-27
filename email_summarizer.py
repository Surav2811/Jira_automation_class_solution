from openai import OpenAI,APIConnectionError
from dotenv import load_dotenv
import os,json
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

class EmailSummarizer:
    def __init__(self):
        # Load environment variables
        load_dotenv()
        
        # Check if required environment variables are present
        required_vars = ["OPEN_AI_BASE_URL", "OPENROUTER_API_KEY", "MODEL_FREE"]
        missing_vars = [var for var in required_vars if not os.getenv(var)]
        
        if missing_vars:
            error_msg = f"Missing required environment variables: {', '.join(missing_vars)}"
            logging.error(error_msg)
            raise EnvironmentError(error_msg)
            
        try:
            # Initialize OpenAI client
            self.client = OpenAI(
                base_url=os.getenv("OPEN_AI_BASE_URL"),
                api_key=os.getenv("OPENROUTER_API_KEY")
            )
            logging.info("OpenAI client initialized successfully")
        except Exception as e:
            logging.error(f"Failed to initialize OpenAI client: {e}")
            raise

    def summarize_email(self, subject, body, sender, recipients):
        """Summarize email content using OpenAI API"""
        prompt = f"""
        You are a highly skilled email processor and summarizer.
        Your task is to summarize the issue described in the email and identify all participants involved.
        
        Subject: {subject}
        From: {sender}
        To: {recipients}
        
        Email Body: {body}
        
        Please provide:
        1. A clear, concise description of the issue (max 100 words)
        2. Key participants and their roles
        3. Priority level (High/Medium/Low) based on content
        4. Category (Technical/Business/Support/Other)
        5. Keep the summary short and it should NOT exceed 100 words
        6. Return the summary in JSON format with the following keys:
            - summary: The summary of the email
            - participants: A list of participants involved in the issue
            - priority: The priority level of the issue (High/Medium/Low)
            - category: The category of the issue (Technical/Business/Support/Other)
        """
        print(prompt)
        try:
            logging.info("Sending summarization request to OpenAI API...")
            completion = self.client.chat.completions.create(
                model=os.getenv("MODEL_FREE"),
                messages=[{"role": "user", "content": prompt}]
            )
            logging.info("Summarization request completed successfully")
            
            # Check if the response is valid
            if completion and completion.choices:
                response = completion.choices[0].message.content
                logging.info(f"Raw response from OpenAI: {response}")  # Log the raw response
                return response
            else:
                logging.error("Received an empty response from OpenAI API.")
                return json.dumps({
                    "summary": "No summary available",
                    "participants": [],
                    "priority": "Low",
                    "category": "Other"
                })
        except json.JSONDecodeError as e:
            logging.error(f"Invalid JSON response: {e}")
            raise
        except APIConnectionError as e:
            logging.error(f"Connection failed: {e}")
            raise
        
# if __name__ == "__main__":
#     try:
#         summarizer = EmailSummarizer()
#         result = summarizer.summarize_email(
#             subject="Test Subject",
#             body="Test Body",
#             sender="test@example.com",
#             recipients="recipient@example.com"
#         )
#         print("Summarization Result:\n", result)
#     except Exception as e:
#         logging.error(f"An error occurred: {e}")