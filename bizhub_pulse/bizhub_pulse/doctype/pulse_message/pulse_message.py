# Copyright (c) 2026, NextTech BizHub and contributors
# License: MIT. See LICENSE

import frappe
from frappe import _
from frappe.model.document import Document

from bizhub_pulse import visibility
from bizhub_pulse.utils import check_space_change, guard_protected


class PulseMessage(Document):
	def validate(self):
		guard_protected(self, ("status", "sent_at"))
		check_space_change(self, field="from_space", contribute=False)
		before = self.get_doc_before_save()
		if before and before.status == "Sent" and not self.flags.pulse_system:
			frappe.throw(_("A sent message cannot be changed."), frappe.PermissionError)
		seen = set()
		for row in self.targets:
			if row.space == self.from_space:
				frappe.throw(_("A message goes to other spaces, not its own."))
			if row.space in seen:
				frappe.throw(_("{0} is listed more than once.").format(row.space))
			seen.add(row.space)
			if not self.flags.pulse_system and not visibility.can_list_space(row.space):
				frappe.throw(_("Space {0} does not exist.").format(row.space))
		if self.from_meeting and frappe.db.get_value("Pulse Meeting", self.from_meeting, "space") != self.from_space:
			frappe.throw(_("The message's meeting belongs to another space."))
