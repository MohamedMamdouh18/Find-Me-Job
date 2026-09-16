import logging
import smtplib
import threading
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

logger = logging.getLogger(__name__)


class EmailService:
    def __init__(
        self, host: str, port: int, user: str, password: str, sender_name: str, cv_path: str
    ):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.sender_name = sender_name
        self.cv_path = cv_path
        self._client = None
        # Sending and quitting both own the connection, and they arrive from
        # different threads: the scheduler sends during a run, the uvicorn
        # threadpool from POST /api/email/send, and a settings change closes the
        # old service from whichever thread saved it. The factory's lock cannot
        # cover this — it is released before the caller sends.
        self._lock = threading.Lock()

    def _connect(self, retries=3, delay=2):
        if not self.user or not self.password:
            raise ValueError("SMTP credentials are not configured")

        for attempt in range(1, retries + 1):
            try:
                if self.port == 465:
                    self._client = smtplib.SMTP_SSL(self.host, self.port, timeout=30)
                else:
                    self._client = smtplib.SMTP(self.host, self.port, timeout=30)
                    self._client.ehlo()
                    self._client.starttls()
                    self._client.ehlo()

                self._client.login(self.user, self.password.strip())
                logger.info(f"SMTP connected as {self.user}")
                return
            except Exception as e:
                logger.warning(f"SMTP connection attempt {attempt}/{retries} failed: {e}")
                self._client = None
                if attempt < retries:
                    time.sleep(delay)

        raise ConnectionError("Failed to connect to SMTP server after retries")

    def _ensure_connection(self):
        """Checks if the connection is alive using NOOP. Reconnects if necessary."""
        if self._client is not None:
            try:
                status, _ = self._client.noop()
                if status == 250:
                    return  # Connection is still alive
            except Exception as e:
                logger.warning(f"SMTP connection dead ({e}), reconnecting...")
                try:
                    self._client.quit()
                except Exception:
                    pass
                self._client = None

        logger.info("Establishing new SMTP connection...")
        self._connect()

    def send_application_email(self, recipient: str, subject: str, body: str) -> str:
        """Constructs and sends the email with the CV attached."""
        with self._lock:
            self._ensure_connection()

            msg = MIMEMultipart()
            msg["From"] = f"{self.sender_name} <{self.user}>"
            msg["To"] = recipient
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain"))

            # Attach CV
            with open(self.cv_path, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
                encoders.encode_base64(part)
                part.add_header("Content-Disposition", "attachment", filename="CV.docx")
                msg.attach(part)

            logger.info(f"Sending email to {recipient} with subject '{subject}'")

            # Guarantee self._client is fresh or alive
            response = self._client.send_message(msg)  # type: ignore
            return str(response)

    def quit(self):
        """Cleanly quits the active SMTP connection if one exists.

        Waits for a send in flight rather than closing the socket underneath it.
        """
        with self._lock:
            if self._client is not None:
                try:
                    self._client.quit()
                    logger.info("SMTP disconnected safely")
                except Exception as e:
                    logger.warning(f"Error disconnecting from SMTP: {e}")
                self._client = None
