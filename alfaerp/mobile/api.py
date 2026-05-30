import secrets

import frappe
from frappe import _


@frappe.whitelist()
def get_api_key_and_secret():
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Authentication required to access API credentials."), frappe.AuthenticationError)

	user_details = frappe.get_doc("User", user)
	api_secret = api_key = ""
	
	if not user_details.api_key and not user_details.api_secret:
		api_secret = frappe.generate_hash(length=15)
		# if api key is not set generate api key
		api_key = frappe.generate_hash(length=15)
		user_details.api_key = api_key
		user_details.api_secret = api_secret
		user_details.save(ignore_permissions=True)
	else:
		api_secret = user_details.get_password("api_secret")
		api_key = user_details.get("api_key")

	return {"api_secret": api_secret, "api_key": api_key}
