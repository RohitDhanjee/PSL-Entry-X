from fastapi import APIRouter, HTTPException
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()  # Load environment variables from .env

router = APIRouter()

class EmailRequest(BaseModel):
    subject: str
    body: str
    to_email: str


import smtplib
from email.message import EmailMessage

def send_email(subject, body, to):
    smtp_server = "smtp.hostinger.com"
    smtp_port = 587
    EMAIL_ADDRESS = "drm@softechdigitalgroup.com"
    EMAIL_PASSWORD = "Scousers999!!!"

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = to
    msg.set_content(body)

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()  # Secure the connection
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.send_message(msg)
            print("Email sent successfully.")
    except Exception as e:
        print("Error sending email:", e)

# def send_email(subject, body, to_email):
#     sender_email = "drm@softechdigitalgroup.com"
#     password = os.getenv("EMAIL_PASSWORD")  # Must be app password

#     msg = MIMEMultipart()
#     msg["From"] = sender_email
#     msg["To"] = to_email
#     msg["Subject"] = subject
#     msg.attach(MIMEText(body, "plain"))

#     try:
#         server = smtplib.SMTP("smtp.gmail.com", 587)  # <-- use Gmail's SMTP
#         server.starttls()
#         server.login(sender_email, password)
#         server.sendmail(sender_email, to_email, msg.as_string())
#         server.quit()
#         return True
#     except Exception as e:
#         print(f"Error sending email: {e}")
#         return False

@router.post("/send")
def send_email_route(request: EmailRequest):
    success = send_email(request.subject, request.body, request.to_email)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to send email")
    return {"message": "Email sent successfully"}
