import frappe
from frappe.tests.utils import FrappeTestCase

from alfaerp.mobile.api import get_api_key_and_secret


class TestApiCredentials(FrappeTestCase):
	def setUp(self):
		self.user = frappe.get_doc(
			{
				"doctype": "User",
				"email": "api.credentials@example.com",
				"first_name": "Api",
				"user_type": "System User",
			}
		)
		self.user.flags.send_welcome_email = False
		self.user.insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")
		if frappe.db.exists("User", self.user.name):
			frappe.delete_doc("User", self.user.name, ignore_permissions=True)

	def test_get_api_key_and_secret_generates_credentials(self):
		frappe.set_user(self.user.name)
		result = get_api_key_and_secret()

		self.assertTrue(result["api_key"])
		self.assertTrue(result["api_secret"])

		user = frappe.get_doc("User", self.user.name)
		self.assertEqual(result["api_key"], user.api_key)
		self.assertEqual(result["api_secret"], user.get_password("api_secret"))

	def test_get_api_key_and_secret_returns_existing_credentials(self):
		frappe.set_user(self.user.name)
		first = get_api_key_and_secret()
		second = get_api_key_and_secret()

		self.assertEqual(first, second)

	def test_get_api_key_and_secret_requires_authentication(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.AuthenticationError):
			get_api_key_and_secret()
