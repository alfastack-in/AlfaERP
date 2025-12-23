import frappe
import requests
import json
from frappe import enqueue
import re
import os
import google.auth.transport.requests
from google.oauth2 import service_account


def get_user_device_details_list(doc):
    user_email = doc.for_user
    user_device_details_list = frappe.get_all(
        "User Device Details", filters={"user": user_email}, fields=["fcm_token"]
    )
    return user_device_details_list


@frappe.whitelist()
def send_notification(doc, method=None):
    user_device_details_list = get_user_device_details_list(doc)
    for device_details in user_device_details_list:
        enqueue(
            process_notification,
            now=False,
            queue="default",
            notification=doc,
            fcm_token=device_details.fcm_token,
        )


def convert_message(message):
    CLEANR = re.compile("<.*?>")
    cleanmessage = re.sub(CLEANR, "", message)
    return cleanmessage


def process_notification(fcm_token, notification):
    message = notification.email_content
    title = notification.subject

    if message:
        message = convert_message(message)
    if title:
        title = convert_message(title)

    body = {
        "message": {
            "token": fcm_token,
            "notification": {
                "title": title,
                "body": message,
            },
            "data": {
                "name": notification.name,
                "type": notification.type,
                "document_type": notification.document_type,
                "document_name": notification.document_name,
            }
        }
    }

    headers = {
        "Authorization": "Bearer " + _get_access_token(),
        "Content-Type": "application/json; UTF-8",
    }

    PROJECT_ID = frappe.db.get_single_value("FCM Settings", "firebase_project_id")
    BASE_URL = "https://fcm.googleapis.com"
    FCM_ENDPOINT = "v1/projects/" + PROJECT_ID + "/messages:send"
    FCM_URL = BASE_URL + "/" + FCM_ENDPOINT

    req = requests.post(url=FCM_URL, data=json.dumps(body), headers=headers)
    frappe.log_error(req.text)


def _get_access_token():
    service_account_info = frappe.db.get_single_value(
        "FCM Settings", "service_account_info"
    )
    credentials = service_account.Credentials.from_service_account_info(
        json.loads(service_account_info),
        scopes=["https://www.googleapis.com/auth/firebase.messaging"],
    )
    request = google.auth.transport.requests.Request()
    credentials.refresh(request)
    return credentials.token
