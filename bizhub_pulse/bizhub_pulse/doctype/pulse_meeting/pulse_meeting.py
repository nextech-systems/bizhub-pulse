# Copyright (c) 2026, NextTech BizHub and contributors
# License: MIT. See LICENSE

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_to_date, flt, format_datetime, get_datetime

from bizhub_pulse import visibility
from bizhub_pulse.utils import active_members, check_space_change, guard_protected

PROTECTED = (
	"status",
	"started_at",
	"concluded_at",
	"published_at",
	"current_section",
	"average_rating",
	"summary",
	"previous_meeting",
	"auto_generated",
	"reminder_sent",
)


class PulseMeeting(Document):
	def before_insert(self):
		space = frappe.get_doc("Pulse Space", self.space)
		self.template = self.template or space.default_template
		self.facilitator = self.facilitator or space.default_facilitator
		self.secretary = self.secretary or space.default_secretary
		self.location = self.location or space.location
		self.join_url = self.join_url or space.join_url
		if not self.sections and self.template:
			for row in frappe.get_doc("Pulse Meeting Template", self.template).sections:
				self.append(
					"sections",
					{
						"section_type": row.section_type,
						"title": row.title,
						"planned_minutes": row.minutes,
						"guidance": row.guidance,
					},
				)
		if not self.attendees:
			for user in active_members(self.space):
				self.append("attendees", {"user": user, "attendance": "Expected"})
		if not self.scheduled_end:
			minutes = sum(r.planned_minutes or 0 for r in self.sections) or space.duration_minutes or 90
			self.scheduled_end = add_to_date(self.scheduled_start, minutes=minutes)
		prev = frappe.get_all(
			"Pulse Meeting",
			filters={"space": self.space, "status": ["!=", "Cancelled"], "scheduled_start": ["<", self.scheduled_start]},
			order_by="scheduled_start desc",
			limit=1,
			pluck="name",
		)
		self.flags.pulse_previous = prev[0] if prev else None

	def validate(self):
		guard_protected(self, PROTECTED)
		if self.is_new():
			self.previous_meeting = self.flags.pulse_previous
		check_space_change(self, contribute=False)
		if not self.title:
			self.title = "{0} · {1}".format(self.space, format_datetime(self.scheduled_start, "d MMM yyyy"))
		if self.scheduled_end and get_datetime(self.scheduled_end) <= get_datetime(self.scheduled_start):
			frappe.throw(_("The meeting must end after it starts."))
		seen = set()
		for row in self.attendees:
			row.attendance = row.attendance or "Expected"
			if row.user in seen:
				frappe.throw(_("{0} is listed more than once.").format(row.user))
			seen.add(row.user)
			if row.rating and not 1 <= row.rating <= 10:
				frappe.throw(_("Ratings are from 1 to 10."))
		ratings = [r.rating for r in self.attendees if r.rating]
		if self.flags.pulse_system or self.is_new() or ratings:
			self.average_rating = flt(sum(ratings) / len(ratings), 1) if ratings else 0
		if self.status == "Published" and not self.flags.pulse_system and not self.is_new():
			before = self.get_doc_before_save()
			if before and before.status == "Published":
				frappe.throw(_("A published meeting cannot be changed."), frappe.PermissionError)

	def on_update(self):
		visibility.clear_cache()
