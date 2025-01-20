import imaplib
import email
from email.header import decode_header
import os
from dotenv import load_dotenv
import logging
from dataclasses import dataclass
from typing import List, Optional
import tempfile

@dataclass
class EmailData:
    subject: str
    body: str
    sender: str
    recipients: List[str]
    cc: List[str]
    attachments: List[str]
    message_id: str

class EmailProcessor:
    def __init__(self):
        load_dotenv()
        self.imap_server = os.getenv("IMAP_SERVER")
        self.email_address = os.getenv("EMAIL")
        self.password = os.getenv("PASSWORD")
        self.temp_dir = tempfile.mkdtemp()
        self.initialize_connection()

    def initialize_connection(self):
        """Initialize connection to IMAP server."""
        try:
            self.imap = imaplib.IMAP4_SSL(self.imap_server)
            self.imap.login(self.email_address, self.password)
            logging.info("Successfully connected to IMAP server")
        except Exception as e:
            logging.error(f"Failed to connect to IMAP server: {e}")
            raise

    def decode_email_subject(self, subject):
        """Decode email subject."""
        decoded_parts = []
        for part, encoding in decode_header(subject):
            if isinstance(part, bytes):
                try:
                    decoded_parts.append(part.decode(encoding or 'utf-8'))
                except:
                    decoded_parts.append(part.decode('utf-8', 'ignore'))
            else:
                decoded_parts.append(part)
        return ' '.join(decoded_parts)

    def get_email_body(self, msg):
        """Extract email body from message."""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    try:
                        return part.get_payload(decode=True).decode()
                    except:
                        return part.get_payload(decode=True).decode('utf-8', 'ignore')
        else:
            try:
                return msg.get_payload(decode=True).decode()
            except:
                return msg.get_payload(decode=True).decode('utf-8', 'ignore')
        return ""

    def save_attachments(self, msg) -> List[str]:
        """Save email attachments and return their file paths."""
        attachment_paths = []
        
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_maintype() == 'multipart':
                    continue
                if part.get('Content-Disposition') is None:
                    continue

                filename = part.get_filename()
                if filename:
                    filepath = os.path.join(self.temp_dir, filename)
                    with open(filepath, 'wb') as f:
                        f.write(part.get_payload(decode=True))
                    attachment_paths.append(filepath)
        
        return attachment_paths

    def parse_email(self, msg) -> EmailData:
        """Parse email message into EmailData object."""
        try:
            subject = self.decode_email_subject(msg["subject"] or "")
            body = self.get_email_body(msg)
            sender = msg["from"]
            recipients = msg["to"].split(',') if msg["to"] else []
            cc = msg["cc"].split(',') if msg["cc"] else []
            attachments = self.save_attachments(msg)
            message_id = msg["message-id"]

            return EmailData(
                subject=subject,
                body=body,
                sender=sender,
                recipients=recipients,
                cc=cc,
                attachments=attachments,
                message_id=message_id
            )
        except Exception as e:
            logging.error(f"Error parsing email: {e}")
            raise

    def cleanup(self):
        """Clean up temporary files and close connections."""
        try:
            import shutil
            shutil.rmtree(self.temp_dir)
            self.imap.logout()
        except Exception as e:
            logging.error(f"Error during cleanup: {e}")

    def __del__(self):
        """Destructor to ensure cleanup."""
        self.cleanup()