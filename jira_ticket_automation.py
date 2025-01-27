import logging
from read_email import EmailProcessor
import os
from dotenv import load_dotenv
import re
from jira import JIRA
import imaplib
import email
import time
#from email_summarizer import EmailSummarizer
from email_processing_dashboard import EmailProcessingDashboard
import uuid
import threading
import sys
import signal
import json  # Import json to handle the response
from openai import OpenAI, APIConnectionError

load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class JiraTicketAutomation:
    def __init__(self, dashboard):
        self.email_processor = EmailProcessor()
        self.email_summarizer = EmailSummarizer()
        self.dashboard = dashboard
        self.jira_project = os.getenv("JIRA_PROJECT_KEY")
        self.issue_type = os.getenv("JIRA_ISSUE_TYPE")
        self.processed_tickets = {}
        self.imap_server = os.getenv("IMAP_SERVER")
        self.email_address = os.getenv("EMAIL")
        self.email_password = os.getenv("PASSWORD")
        self.running = True
        
        self.initialize_jira_client()
        self.initialize_imap_client()

    def initialize_jira_client(self):
        """Initialize Jira client with API credentials."""
        try:
            self.jira_server = os.getenv("JIRA_SERVER")
            self.jira_email = os.getenv("JIRA_EMAIL")
            self.jira_api_token = os.getenv("JIRA_API_TOKEN")
            
            self.jira = JIRA(
                server=self.jira_server,
                basic_auth=(self.jira_email, self.jira_api_token)
            )
            logging.info("Jira client initialized successfully")
        except Exception as e:
            logging.error(f"Failed to initialize Jira client: {e}")
            raise

    def initialize_imap_client(self):
        """Initialize IMAP client for real-time email monitoring."""
        try:
            logging.info(f"IMAP Server: {self.imap_server}")
            logging.info(f"Email Address: {self.email_address}")
            
            self.imap = imaplib.IMAP4_SSL(self.imap_server)
            self.imap.login(self.email_address, self.email_password)
            logging.info("IMAP client initialized successfully")
        except Exception as e:
            logging.error(f"Failed to initialize IMAP client: {e}")
            raise

    def categorize_email(self, email):
        """Categorize email as spam, promotional, new issue or existing issue."""
        spam_keywords = ['spam', 'advertisement', 'promotion', 'offer', 'deal']
        if any(keyword in email.subject.lower() for keyword in spam_keywords):
            return 'spam'
            
        ticket_pattern = r'[A-Z]+-\d+'
        ticket_refs = re.findall(ticket_pattern, email.subject)
        if ticket_refs:
            return 'existing', ticket_refs[0]
            
        return 'new'

    def create_jira_ticket(self, issue_dict, attachments):
        """Create a new Jira ticket using REST API."""
        try:
            issue = self.jira.create_issue(fields=issue_dict)
            if attachments:
                for attachment in attachments:
                    with open(attachment, 'rb') as file:
                        self.jira.add_attachment(issue=issue, attachment=file)
            self.processed_tickets[issue.key] = True
            return issue.key
        except Exception as e:
            logging.error(f"Error creating Jira ticket: {e}")
            return None

    def update_jira_ticket(self, ticket_key, email):
        """Update existing Jira ticket with new information using REST API."""
        try:
            issue = self.jira.issue(ticket_key)
            comment = f"Additional information from {email.sender}:\n{email.body}"
            issue.add_comment(comment)
            if email.attachments:
                for attachment in email.attachments:
                    with open(attachment, 'rb') as file:
                        self.jira.add_attachment(issue=issue, attachment=file)
            return True
        except Exception as e:
            logging.error(f"Error updating ticket {ticket_key}: {e}")
            return False

    def process_new_email(self, email_msg):
        """Process a single new email message."""
        email_id = str(uuid.uuid4())
        try:
            email_data = self.email_processor.parse_email(email_msg)
            self.dashboard.update_status(email_id, "Processing", "Email received")
            
            try:
                logging.info(f"Getting summary for email {email_id}...")
                summary_response = self.email_summarizer.summarize_email(
                    email_data.subject,
                    email_data.body,
                    email_data.sender,
                    email_data.recipients
                )
                
                # Parse the JSON response
                summary_data = json.loads(summary_response)
                summary = summary_data.get("summary", "No summary available")
                participants = summary_data.get("participants", [])
                priority = summary_data.get("priority", "Low")
                category = summary_data.get("category", "Other")
                
                self.dashboard.update_status(email_id, "Processing", f"Summary: {summary[:100]}...")
                
            except Exception as e:
                error_msg = f"Summarization failed: {str(e)}"
                logging.error(error_msg)
                self.dashboard.update_status(email_id, "Failed", error_msg)
                return

            category = self.categorize_email(email_data)
            if category == 'spam':
                self.dashboard.update_status(email_id, "Skipped", "Spam detected")
                return

            try:
                if isinstance(category, tuple) and category[0] == 'existing':
                    ticket_key = category[1]
                    if self.update_jira_ticket(ticket_key, email_data):
                        self.dashboard.update_status(email_id, "Completed", f"Updated ticket {ticket_key}")
                else:
                    issue_dict = {
                        "project": {"key": self.jira_project},
                        "summary": email_data.subject,
                        "description": f"Summary:\n{summary}\n",
                        "issuetype": {"name": self.issue_type},
                    }
                    issue_key = self.create_jira_ticket(issue_dict, email_data.attachments)
                    if issue_key:
                        self.dashboard.update_status(email_id, "Completed", f"Created ticket {issue_key}")
                    else:
                        self.dashboard.update_status(email_id, "Failed", "Failed to create ticket")
                        
            except Exception as e:
                error_msg = f"Error processing ticket: {str(e)}"
                logging.error(error_msg)
                self.dashboard.update_status(email_id, "Failed", error_msg)
                
        except Exception as e:
            error_msg = f"Error processing email: {str(e)}"
            logging.error(error_msg)
            self.dashboard.update_status(email_id, "Failed", error_msg)

    def monitor_inbox(self):
        """Continuously monitor inbox for new emails."""
        try:
            while self.running:
                self.imap.select('INBOX')
                _, messages = self.imap.search(None, 'UNSEEN')
                
                for msg_num in messages[0].split():
                    if not self.running:
                        break
                    try:
                        _, msg_data = self.imap.fetch(msg_num, '(RFC822)')
                        email_body = msg_data[0][1]
                        email_msg = email.message_from_bytes(email_body)
                        
                        logging.info(f"Processing new email: {email_msg['subject']}")
                        self.process_new_email(email_msg)
                        
                    except Exception as e:
                        logging.error(f"Error processing message {msg_num}: {e}")
                
                time.sleep(1)
                
        except Exception as e:
            logging.error(f"Error in inbox monitoring: {e}")
            raise

    def stop(self):
        """Stop the monitoring process"""
        self.running = False

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
        """Summarize email content using OpenAI-compatible API"""
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
        try:
            logging.info("Sending summarization request to API...")
            model = os.getenv("MODEL_FREE") 
            
            completion = self.client.chat.completions.create(
                model=model,
                messages=[{
                    "role": "user",
                    "content": [{
                        "type": "text",
                        "text": prompt
                    }]
                }],
                response_format={"type": "json_object"},
                extra_headers={
                    "HTTP-Referer": "<YOUR_SITE_URL>",  
                    "X-Title": "<YOUR_APP_NAME>",       
                }
            )
            
            if completion :
                (logging.info("Summarization request completed successfully"))
                return completion.choices[0].message.content
            
        except Exception as e:
            logging.error(f"API Error: {str(e)}")
            return json.dumps({
                "summary": "Summary unavailable due to processing error",
                "participants": [],
                "priority": "Low",
                "category": "Other"
            })

def main():
    """Initialize and run the automation service."""
    try:
        dashboard = EmailProcessingDashboard()
        
        automation = JiraTicketAutomation(dashboard)
        
        monitor_thread = threading.Thread(
            target=automation.monitor_inbox,
            daemon=True
        )
        
        def signal_handler(signum, frame):
            logging.info("Received shutdown signal, cleaning up...")
            automation.stop()
            dashboard.cleanup()
            sys.exit(0)
            
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        monitor_thread.start()
        
        logging.info("Starting dashboard...")
        dashboard.launch()  # Open in a new tab
        while True:
            time.sleep(1)
        
    except Exception as e:
        logging.error(f"Failed to start services: {e}")
        raise

if __name__ == "__main__":
    main()