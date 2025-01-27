import gradio as gr
import pandas as pd
from datetime import datetime
import queue
import threading
import time
import logging

class EmailProcessingDashboard:
    def __init__(self):
        self.email_queue = queue.Queue()
        self.processing_status = {}
        self.lock = threading.Lock()
        self.should_run = True
        
        # Initialize the interface
        self.create_interface()

    def create_interface(self):
        with gr.Blocks(theme=gr.themes.Default()) as self.interface:
            gr.Markdown("# Email Processing Dashboard")
            
            with gr.Row():
                with gr.Column():
                    gr.Markdown("### Processing Statistics")
                    self.emails_processed = gr.Number(label="Emails Processed", value=0)
                    self.emails_in_queue = gr.Number(label="Emails in Queue", value=0)
                    self.success_rate = gr.Number(label="Success Rate (%)", value=100)

            with gr.Row():
                self.status_table = gr.DataFrame(
                    headers=["Email ID", "Status", "Timestamp", "Details"],
                    label="Processing Status",
                    value=pd.DataFrame(columns=["Email ID", "Status", "Timestamp", "Details"])
                )

            refresh_btn = gr.Button("Refresh Dashboard")
            refresh_btn.click(
                fn=self.update_dashboard,
                outputs=[
                    self.emails_processed,
                    self.emails_in_queue,
                    self.success_rate,
                    self.status_table
                ],
                show_progress=False
            )

            # Auto-refresh using interval
            gr.HTML("""
                <script>
                    function autoRefresh() {
                        const refreshButton = document.querySelector('button:contains("Refresh Dashboard")');
                        if (refreshButton) {
                            refreshButton.click();
                        }
                    }
                    setInterval(autoRefresh, 5000);
                </script>
            """)

    def update_status(self, email_id, status, details=""):
        """Update status and trigger dashboard refresh"""
        with self.lock:
            self.processing_status[email_id] = {
                "status": status,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "details": details
            }
            logging.info(f"Status updated for {email_id}: {status} - {details}")

    def get_status_df(self):
        with self.lock:
            if not self.processing_status:
                return pd.DataFrame(columns=["Email ID", "Status", "Timestamp", "Details"])
            
            data = [
                {
                    "Email ID": email_id,
                    "Status": info["status"],
                    "Timestamp": info["timestamp"],
                    "Details": info["details"]
                }
                for email_id, info in self.processing_status.items()
            ]
            return pd.DataFrame(data)

    def update_dashboard(self):
        """Update dashboard with current statistics"""
        try:
            with self.lock:
                total_processed = len([s for s in self.processing_status.values() if s["status"] == "Completed"])
                queue_size = self.email_queue.qsize()
                success_rate = self.calculate_success_rate()
                status_df = self.get_status_df()
                
                logging.info(f"Dashboard updated: {total_processed} processed, {queue_size} in queue")
                
                return [
                    total_processed,
                    queue_size,
                    success_rate,
                    status_df.to_dict('records')
                ]
        except Exception as e:
            logging.error(f"Error updating dashboard: {e}")
            # Return default values in case of error
            return [0, 0, 100, []]

    def calculate_success_rate(self):
        with self.lock:
            completed = len([s for s in self.processing_status.values() if s["status"] == "Completed"])
            total = len(self.processing_status)
            return round((completed / total * 100) if total > 0 else 100, 2)

    def launch(self):
        """Launch the dashboard interface"""
        try:
            self.interface.queue()
            self.interface.launch(
                share=True, 
                show_error=True,
                prevent_thread_lock=True
            )
        except Exception as e:
            logging.error(f"Error launching dashboard: {e}")
            raise

    def cleanup(self):
        """Cleanup resources"""
        self.should_run = False