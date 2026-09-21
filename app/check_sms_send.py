"""
Direct test of send_sms() — including the curl fallback if the normal
path fails — without going through USSD/ngrok at all.

Run from inside app/:
    python check_sms_send.py
"""

import os
from dotenv import load_dotenv
load_dotenv()

from sms_client import send_sms

if __name__ == "__main__":
    phone = "+254700000000"  # any fake number works in the sandbox
    print(f"Sending a test SMS to {phone} (sandbox — not a real phone)...")
    result = send_sms(phone, "Test message from Bill Bridge — checking the send path works.")
    print("\nResult:")
    print(result)