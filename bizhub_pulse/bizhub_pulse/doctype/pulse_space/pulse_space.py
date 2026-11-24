# Copyright (c) 2026, NextTech BizHub and contributors
# License: MIT. See LICENSE

import frappe
from frappe import _
from frappe.model.document import Document

from bizhub_pulse import visibility


class PulseSpace(Document):
	def validate(self):
		if self.space_type == "Person" and not self.person_user:
			frappe.throw(_("A Person space needs the person it belongs to."))
		if self.space_type != "Person":
			self.person_user = None
		if self.space_type == "Company":
			self.visibility = "Private"
		seen = set()
		for row in self.members:
			if row.user in seen:
				frappe.throw(_("{0} is listed more than once.").format(row.user))
			seen.add(row.user)
		if self.parent_space == self.name:
			frappe.throw(_("A space cannot be its own parent."))
		if (self.duration_minutes or 0) < 0 or (self.schedule_ahead_days or 0) < 0:
			frappe.throw(_("Length and days ahead cannot be negative."))
		if self.cadence in ("Weekly", "Fortnightly") and not self.meeting_weekday:
			frappe.throw(_("Choose the weekday for this meeting rhythm."))
		self._guard_leader_changes()

	def _guard_leader_changes(self):
		"""A Leader manages members but cannot change the space's type or visibility."""
		if self.is_new() or visibility.is_admin():
			return
		before = self.get_doc_before_save()
		for field in ("space_type", "visibility", "person_user", "disabled"):
			if before and before.get(field) != self.get(field):
				frappe.throw(_("Only a Pulse Admin can change {0}.").format(self.meta.get_label(field)), frappe.PermissionError)

	def on_update(self):
		visibility.clear_cache()

	def on_trash(self):
		visibility.clear_cache()
