import frappe
from frappe import _


@frappe.whitelist()
def get_api_key_and_secret():
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Authentication required to access API credentials."), frappe.AuthenticationError)

	user_details = frappe.get_doc("User", user)
	api_key = user_details.get("api_key")
	api_secret = None

	if user_details.api_secret:
		api_secret = user_details.get_password("api_secret")

	updated = False
	if not api_key:
		api_key = frappe.generate_hash(length=15)
		user_details.api_key = api_key
		updated = True

	if not api_secret:
		api_secret = frappe.generate_hash(length=15)
		user_details.api_secret = api_secret
		updated = True

	if updated:
		user_details.save(ignore_permissions=True)

	return {"api_key": api_key, "api_secret": api_secret}
