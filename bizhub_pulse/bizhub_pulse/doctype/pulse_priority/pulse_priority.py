# Copyright (c) 2026, NextTech BizHub and contributors
# License: MIT. See LICENSE

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, today

from bizhub_pulse import visibility
from bizhub_pulse.utils import changed, check_space_change, guard_protected

# The owner keeps the priority up to date; only leaders change what was agreed.
AGREED = ("title", "space", "priority_owner", "kind", "quarter", "due_date", "success_criteria",
	"measure_name", "unit", "start_value", "target_value", "visibility")


class PulsePriority(Document):
	def validate(self):
		guard_protected(self, ("closed_on", "current_as_of"))
		check_space_change(self, contribute=False)
		self._limit_owner_changes()
		if self.kind == "Measured":
			if self.target_value is None:
				frappe.throw(_("A measured priority needs a target."))
			self.milestones = []
			if self.is_new() or changed(self, "current_value"):
				self.flags.pulse_system = True
				self.current_as_of = today()
		else:
			for field in ("measure_name", "unit", "start_value", "target_value", "current_value", "current_as_of"):
				self.set(field, None)
			for row in self.milestones:
				if row.done and not row.done_on:
					row.done_on = today()
				if not row.done:
					row.done_on = None
			if self.status in ("On Track", "Off Track"):
				self.status = "Off Track" if self.overdue_milestones() else "On Track"
		if self.status in ("Done", "Dropped"):
			if not self.closed_on:
				self.flags.pulse_system = True
				self.closed_on = today()
		elif self.closed_on:
			self.flags.pulse_system = True
			self.closed_on = None
		seen = set()
		for row in self.contributors:
			if row.user in seen:
				frappe.throw(_("{0} is listed more than once.").format(row.user))
			seen.add(row.user)

	def overdue_milestones(self):
		day = getdate(today())
		return [r for r in self.milestones if not r.done and r.due_date and getdate(r.due_date) < day]

	def _limit_owner_changes(self):
		"""The owner updates progress; changing the commitment itself needs a space leader."""
		if self.is_new() or self.flags.pulse_system:
			return
		user = frappe.session.user
		before = self.get_doc_before_save()
		if visibility.is_admin(user) or visibility.can_manage(before.space, user):
			return
		for field in AGREED:
			if changed(self, field):
				frappe.throw(
					_("{0} was agreed with the space's leaders. Ask a leader to change it.").format(self.meta.get_label(field)),
					frappe.PermissionError,
				)
		before_rows = {(r.milestone, str(r.due_date), r.milestone_owner) for r in before.milestones}
		after_rows = {(r.milestone, str(r.due_date), r.milestone_owner) for r in self.milestones}
		if before_rows != after_rows:
			frappe.throw(_("Ask a space leader to add, remove or re-date milestones. You can tick them done."), frappe.PermissionError)
