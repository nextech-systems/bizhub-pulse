# Copyright (c) 2026, NextTech BizHub and contributors
# License: MIT. See LICENSE

import frappe
from frappe import _
from frappe.model.document import Document

from bizhub_pulse.utils import check_space_change, guard_protected


class PulseHeadline(Document):
	def before_validate(self):
		if self.is_new() and not self.flags.pulse_system:
			self.author = frappe.session.user
			self.flags.pulse_auto = {"author"}

	def validate(self):
		guard_protected(self, ("author",))
		check_space_change(self)
		if self.meeting and frappe.db.get_value("Pulse Meeting", self.meeting, "space") != self.space:
			frappe.throw(_("The headline's meeting belongs to another space."))
