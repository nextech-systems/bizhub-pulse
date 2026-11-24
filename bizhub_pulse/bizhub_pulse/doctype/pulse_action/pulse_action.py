# Copyright (c) 2026, NextTech BizHub and contributors
# License: MIT. See LICENSE

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import today

from bizhub_pulse import visibility
from bizhub_pulse.utils import changed, check_reference, check_space_change, default_due_date, guard_protected

PROTECTED = ("assigned_by", "carried_over", "completed_on", "verified_by", "verified_on", "source_meeting", "reviewed_in", "message")
OWNER_FIELDS = {"status", "completion_note", "evidence"}


class PulseAction(Document):
	def before_validate(self):
		if self.is_new() and not self.flags.pulse_system:
			self.assigned_by = frappe.session.user
			self.flags.pulse_auto = {"assigned_by"}
		if not self.due_date:
			self.due_date = default_due_date()

	def validate(self):
		guard_protected(self, PROTECTED)
		check_space_change(self)
		check_reference(self)
		if not frappe.db.get_value("User", self.assigned_to, "enabled"):
			frappe.throw(_("{0} is not an active user.").format(self.assigned_to))
		self._limit_owner_changes()
		if self.status == "Done":
			if self.evidence_required and not (self.completion_note or self.evidence):
				frappe.throw(_("This action needs a completion note or evidence before it can be marked Done."))
			if not self.completed_on:
				self.flags.pulse_system = True
				self.completed_on = today()
		elif self.completed_on and changed(self, "status"):
			self.flags.pulse_system = True
			self.completed_on = None
			self.verified_by = None
			self.verified_on = None
		for field, doctype in (("issue", "Pulse Issue"), ("decision", "Pulse Decision"), ("priority", "Pulse Priority")):
			ref = self.get(field)
			if ref and frappe.db.get_value(doctype, ref, "space") != self.space:
				frappe.throw(_("The linked {0} belongs to another space.").format(doctype))

	def _limit_owner_changes(self):
		"""The action's owner (alone) may update its status, note and evidence, nothing else."""
		if self.is_new() or self.flags.pulse_system:
			return
		user = frappe.session.user
		before = self.get_doc_before_save()
		if visibility.is_admin(user) or user == before.assigned_by or visibility.can_manage(before.space, user):
			return
		for df in self.meta.fields:
			if df.fieldname not in OWNER_FIELDS and changed(self, df.fieldname):
				frappe.throw(
					_("As the owner you can update the status, note and evidence. Ask {0} to change anything else.").format(
						before.assigned_by
					),
					frappe.PermissionError,
				)
		if self.status == "Cancelled" and changed(self, "status"):
			frappe.throw(_("Ask {0} to cancel this action.").format(before.assigned_by), frappe.PermissionError)
