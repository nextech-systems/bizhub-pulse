# Copyright (c) 2026, NextTech BizHub and contributors
# License: MIT. See LICENSE

import frappe
from frappe import _
from frappe.model.document import Document


class PulseMeetingNotes(Document):
	def validate(self):
		self.space = frappe.db.get_value("Pulse Meeting", self.meeting, "space")
		if not self.space:
			frappe.throw(_("Meeting {0} does not exist.").format(self.meeting))
