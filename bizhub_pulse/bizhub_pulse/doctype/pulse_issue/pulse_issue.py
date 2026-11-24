# Copyright (c) 2026, NextTech BizHub and contributors
# License: MIT. See LICENSE

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, today

from bizhub_pulse.utils import changed, check_reference, check_space_change, guard_protected

PROTECTED = ("raised_by", "raised_in", "solved_in", "closed_on", "escalated_to", "escalated_issue", "escalated_from")


class PulseIssue(Document):
	def before_validate(self):
		if self.is_new() and not self.flags.pulse_system:
			self.raised_by = frappe.session.user
			self.flags.pulse_auto = {"raised_by"}
		if self.is_new() and not self.issue_owner:
			self.issue_owner = self.raised_by
		if self.is_new() and not cint(self.rank):
			top = frappe.db.sql(
				"select max(`rank`) from `tabPulse Issue` where space=%s and status='Open'", (self.space,)
			)[0][0]
			self.rank = cint(top) + 1

	def validate(self):
		guard_protected(self, PROTECTED)
		check_space_change(self)
		check_reference(self)
		if self.get("priority") and frappe.db.get_value("Pulse Priority", self.priority, "space") != self.space:
			frappe.throw(_("The linked priority belongs to another space."))
		if self.status == "Escalated" and (self.is_new() or changed(self, "status")) and not self.flags.pulse_system:
			frappe.throw(_("Use Escalate to send an issue to another space."))
		if self.status in ("Solved", "Dropped") and (self.is_new() or changed(self, "status")):
			self.flags.pulse_system = True
			self.closed_on = today()
		if self.status == "Open" and changed(self, "status"):
			self.flags.pulse_system = True
			self.closed_on = None
			self.solved_in = None
