import frappe
import requests
import json
from frappe import enqueue
import re
import os

import google.auth.transport.requests
from google.oauth2 import service_account


def user_id(doc):
    user_email = doc.for_user
    user_device_id = frappe.get_all(
        "User Device Details", filters={"user": user_email}, fields=["fcm_token"]
    )
    return user_device_id


@frappe.whitelist()
def send_notification(doc,method=None):
    device_ids = user_id(doc)
    for device_id in device_ids:
        enqueue(
            process_notification,
            queue="default",
            now=False,
            device_id=device_id,
            notification=doc,
        )


def convert_message(message):
    CLEANR = re.compile("<.*?>")
    cleanmessage = re.sub(CLEANR, "", message)
    return cleanmessage


def process_notification(device_id, notification):
    message = notification.email_content
    title = notification.subject

    if message:
        message = convert_message(message)
    if title:
        title = convert_message(title)

    body = {
        "message":{
            "token": device_id.device_id,
            "notification":{
                "body": message,
                "title": title
            }
        }
    }

    headers = {
        'Authorization': 'Bearer ' + _get_access_token(),
        'Content-Type': 'application/json; UTF-8',
    }

    req = requests.post(
        url=FCM_URL,
        data=json.dumps(body),
        headers=headers
    )
    frappe.log_error(req.text)

PROJECT_ID = 'alfaerp-bd38a'
BASE_URL = 'https://fcm.googleapis.com'
FCM_ENDPOINT = 'v1/projects/' + PROJECT_ID + '/messages:send'
FCM_URL = BASE_URL + '/' + FCM_ENDPOINT
SCOPES = ['https://www.googleapis.com/auth/firebase.messaging']

def _get_access_token():
    service_account_path = os.path.join(
        frappe.get_app_path('fcm_notification'), 
        'service-account.json'
    )
    credentials = service_account.Credentials.from_service_account_file(
        service_account_path, 
        scopes=SCOPES
    )
    request = google.auth.transport.requests.Request()
    credentials.refresh(request)
    return credentials.token