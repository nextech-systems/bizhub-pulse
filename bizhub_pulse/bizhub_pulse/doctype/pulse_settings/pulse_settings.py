# Copyright (c) 2026, NextTech BizHub and contributors
# License: MIT. See LICENSE

import frappe
from frappe import _
from frappe.model.document import Document


class PulseSettings(Document):
	def validate(self):
		if (self.default_due_days or 0) < 1:
			frappe.throw(_("Actions need at least one day before they are due."))


@frappe.whitelist()
def employees_without_manager():
	"""Count active employees with a user but no reports_to (for the settings page)."""
	frappe.only_for(("Pulse Admin", "System Manager"))
	rows = frappe.get_all(
		"Employee",
		filters={"status": "Active", "user_id": ["is", "set"], "reports_to": ["is", "not set"]},
		fields=["name", "employee_name"],
		order_by="employee_name asc",
	)
	return rows
