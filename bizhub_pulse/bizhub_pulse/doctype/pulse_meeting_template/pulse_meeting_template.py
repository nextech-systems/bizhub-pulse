# Copyright (c) 2026, NextTech BizHub and contributors
# License: MIT. See LICENSE

import frappe
from frappe import _
from frappe.model.document import Document


class PulseMeetingTemplate(Document):
	def validate(self):
		if not self.sections:
			frappe.throw(_("A template needs at least one section."))
		for row in self.sections:
			if (row.minutes or 0) <= 0:
				frappe.throw(_("Row {0}: minutes must be more than zero.").format(row.idx))
		self.total_minutes = sum(row.minutes or 0 for row in self.sections)
