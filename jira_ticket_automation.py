import asyncio
import logging
from read_email import EmailProcessor
import os
from dotenv import load_dotenv
import re
from jira import JIRA
from send_email import send_email
import signal
import sys
import imaplib
import email
import uuid

# Load environment variables
load_dotenv()

# Configure logging to write to a file in the same directory as the script
log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'jira_ticket_automation.log')
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),  # Log to a file
        logging.StreamHandler()         # Also log to the console
    ]
)

class JiraTicketAutomation:
    def __init__(self):
        self.email_processor = EmailProcessor()
        self.jira_project = os.getenv("JIRA_PROJECT_KEY")
        self.issue_type = os.getenv("JIRA_ISSUE_TYPE")
        self.processed_tickets = {}
        self.imap_server = os.getenv("IMAP_SERVER")
        self.email_address = os.getenv("EMAIL")
        self.email_password = os.getenv("PASSWORD")
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
            self.imap = imaplib.IMAP4_SSL(self.imap_server)
            self.imap.login(self.email_address, self.email_password)
            logging.info("IMAP client initialized successfully")
        except Exception as e:
            logging.error(f"Failed to initialize IMAP client: {e}")
            raise

    def categorize_email(self, email):
        """Categorize email as spam, promotional, new issue or existing issue."""
        # Basic spam/promo detection
        spam_keywords = ['spam', 'advertisement', 'promotion', 'offer', 'deal']
        if any(keyword in email.subject.lower() for keyword in spam_keywords):
            return 'spam'
            
        # Check if this is a reply to an existing ticket
        ticket_pattern = r'[A-Z]+-\d+'
        ticket_refs = re.findall(ticket_pattern, email.subject)
        if ticket_refs:
            return 'existing', ticket_refs[0]
            
        return 'new'

    def create_jira_ticket(self, issue_dict, attachments):
        """Create a new Jira ticket using REST API."""
        try:
            # Create the issue using JIRA API
            issue = self.jira.create_issue(fields=issue_dict)
            
            # Add attachments if any
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
            
            # Add comment
            comment = f"Additional information from {email.sender}:\n{email.body}"
            issue.add_comment(comment)
            
            # Add new attachments
            if email.attachments:
                for attachment in email.attachments:
                    with open(attachment, 'rb') as file:
                        self.jira.add_attachment(issue=issue, attachment=file)
            
            return True
            
        except Exception as e:
            logging.error(f"Error updating ticket {ticket_key}: {e}")
            return False

    async def process_new_email(self, email_msg):
        """Process a single new email message asynchronously."""
        try:
            email_data = self.email_processor.parse_email(email_msg)
            email_id = str(uuid.uuid4())
            
            # Categorize email
            category = self.categorize_email(email_data)
            
            if category == 'spam':
                logging.info(f"Skipping spam/promotional email from {email_data.sender}")
                return
            
            if isinstance(category, tuple) and category[0] == 'existing':
                # Handle existing ticket update
                ticket_key = category[1]
                if self.update_jira_ticket(ticket_key, email_data):
                    subject = f"Jira Ticket Updated: {ticket_key}"
                    body = f"Your email has been added to existing Jira ticket.\n\nTicket Key: {ticket_key}"
                    send_email(email_data.sender, subject, body)
                    logging.info(f"Updated Jira ticket {ticket_key} for {email_data.sender}")
            else:
                # Create new ticket
                issue_dict = {
                    "project": {"key": self.jira_project},
                    "summary": email_data.subject,
                    "description": f"Full Email:\n{email_data.body}",
                    "issuetype": {"name": self.issue_type},
                }
                
                issue_key = self.create_jira_ticket(issue_dict, email_data.attachments)
                
                if issue_key:
                    subject = f"Jira Ticket Created: {issue_key}"
                    body = f"A new Jira ticket has been created for your email.\n\nSubject: {email_data.subject}\nTicket Key: {issue_key}"
                    send_email(email_data.sender, subject, body)
                    logging.info(f"Created new Jira ticket {issue_key} for {email_data.sender}")
            
        except Exception as e:
            logging.error(f"Error processing email: {e}", exc_info=True)

    async def monitor_inbox(self):
        """Continuously monitor inbox for new emails asynchronously."""
        try:
            while True:
                try:
                    self.imap.select('INBOX')
                    _, messages = self.imap.search(None, 'UNSEEN')
                    for msg_num in messages[0].split():
                        try:
                            # Fetch the email message
                            _, msg_data = self.imap.fetch(msg_num, '(RFC822)')
                            email_body = msg_data[0][1]
                            email_msg = email.message_from_bytes(email_body)
                            
                            logging.info(f"Processing new email: {email_msg['subject']}")
                            await self.process_new_email(email_msg)
                            
                            # Mark the email as seen
                            self.imap.store(msg_num, '+FLAGS', '\\Seen')
                        except Exception as e:
                            logging.error(f"Error processing message {msg_num}: {e}", exc_info=True)
                    
                    # Short sleep to prevent excessive CPU usage
                    await asyncio.sleep(1)
                except imaplib.IMAP4.abort:
                    logging.warning("IMAP connection lost. Reconnecting...")
                    self.initialize_imap_client()
        except Exception as e:
            logging.error(f"Error in inbox monitoring: {e}", exc_info=True)
            raise

class AutomationService:
    def __init__(self):
        self.automation = JiraTicketAutomation()
        signal.signal(signal.SIGTERM, self.handle_signal)
        signal.signal(signal.SIGINT, self.handle_signal)

    def handle_signal(self, signum, frame):
        logging.info(f"Received signal {signum}. Shutting down...")
        sys.exit(0)

    async def run(self):
        """Run the automation service asynchronously."""
        try:
            logging.info("Starting Jira ticket automation service...")
            await self.automation.monitor_inbox()
        except Exception as e:
            logging.error(f"Service error: {e}")

async def main():
    """Initialize and run the automation service asynchronously."""
    service = AutomationService()
    await service.run()

if __name__ == "__main__":
    asyncio.run(main())