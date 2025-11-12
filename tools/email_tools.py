import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import os

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = r"D:\Projects\Godrej\adk-ws\service_account_key.json"

def send_email_via_smtp(
    subject: str,
    body: str,
    recipient_email: str = "abthakare2011@gmail.com",
    sender_email: str = "ankitathakare0207@gmail.com",
    smtp_server: str = "smtp.gmail.com",
    smtp_port: int = 587,
    smtp_password: str = "lcqz rssj ikar lybj"
) -> dict:
    try:
        msg = MIMEMultipart()
        msg["From"] = sender_email
        msg["To"] = recipient_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, smtp_password)
            server.send_message(msg)

        return {"status": "success", "message": "Email sent successfully"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
