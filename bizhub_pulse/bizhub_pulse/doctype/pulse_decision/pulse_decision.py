# Copyright (c) 2026, NextTech BizHub and contributors
# License: MIT. See LICENSE

import frappe
from frappe import _
from frappe.model.document import Document

from bizhub_pulse.utils import changed, check_reference, check_space_change, guard_protected

EDITABLE_WHEN_LOCKED = {"status", "superseded_by", "review_date"}


class PulseDecision(Document):
	def before_validate(self):
		if self.is_new() and not self.approved_by:
			self.approved_by = frappe.session.user
		if self.meeting and not self.space:
			self.space = frappe.db.get_value("Pulse Meeting", self.meeting, "space")

	def validate(self):
		guard_protected(self, ("locked", "superseded_by"))
		check_space_change(self, contribute=False)
		check_reference(self)
		if self.get("priority") and frappe.db.get_value("Pulse Priority", self.priority, "space") != self.space:
			frappe.throw(_("The linked priority belongs to another space."))
		if self.meeting and frappe.db.get_value("Pulse Meeting", self.meeting, "space") != self.space:
			frappe.throw(_("The decision's meeting belongs to another space."))
		if self.issue and frappe.db.get_value("Pulse Issue", self.issue, "space") != self.space:
			frappe.throw(_("The decision's issue belongs to another space."))
		if self.supersedes:
			if self.supersedes == self.name:
				frappe.throw(_("A decision cannot supersede itself."))
			if frappe.db.get_value("Pulse Decision", self.supersedes, "space") != self.space:
				frappe.throw(_("A decision can only supersede one from the same space."))
		before = self.get_doc_before_save()
		if before and before.locked and not self.flags.pulse_system:
			for df in self.meta.fields:
				if df.fieldname not in EDITABLE_WHEN_LOCKED and changed(self, df.fieldname):
					frappe.throw(
						_("This decision was published. Record a new decision that supersedes it instead of editing it."),
						frappe.PermissionError,
					)

	def on_update(self):
		if self.supersedes and (self.flags.in_insert or changed(self, "supersedes")):
			old = frappe.get_doc("Pulse Decision", self.supersedes)
			old.flags.pulse_system = True
			old.status = "Superseded"
			old.superseded_by = self.name
			old.save(ignore_permissions=True)
