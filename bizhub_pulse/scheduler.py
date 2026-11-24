# Copyright (c) 2026, NextTech BizHub and contributors
# License: MIT. See LICENSE
"""Scheduled jobs: recurring meetings, the daily digest and meeting reminders."""

import datetime

import frappe
from frappe import _
from frappe.utils import add_days, cint, get_datetime, getdate, today

from bizhub_pulse.utils import enabled_users, settings

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def occurrences(space, start, end):
	"""Meeting dates for a space's rhythm between start and end (inclusive)."""
	if space.cadence == "Weekdays":
		day = start
		while day <= end:
			if day.weekday() < 5:
				yield day
			day = add_days(day, 1)
		return
	if space.cadence not in ("Weekly", "Fortnightly") or not space.meeting_weekday:
		return
	target = WEEKDAYS.index(space.meeting_weekday)
	step = 7 if space.cadence == "Weekly" else 14
	# Anchor fortnightly rhythms to ISO week parity so reruns produce the same dates.
	day = start + datetime.timedelta(days=(target - start.weekday()) % 7)
	if step == 14 and day.isocalendar()[1] % 2:
		day = add_days(day, 7)
	while day <= end:
		yield day
		day = add_days(day, step)


def generate_meetings():
	"""Create upcoming meetings from each space's rhythm. Safe to run more than once."""
	start = getdate(today())
	for space in frappe.get_all(
		"Pulse Space",
		filters={"disabled": 0, "cadence": ["in", ["Weekly", "Fortnightly", "Weekdays"]]},
		fields=["name", "cadence", "meeting_weekday", "meeting_time", "schedule_ahead_days"],
	):
		end = add_days(start, cint(space.schedule_ahead_days) or 14)
		existing = {
			getdate(d)
			for d in frappe.get_all(
				"Pulse Meeting",
				filters={"space": space.name, "scheduled_start": ["between", [start, add_days(end, 1)]]},
				pluck="scheduled_start",
			)
		}
		for day in occurrences(space, start, end):
			if day in existing:
				continue
			when = get_datetime(f"{day} {space.meeting_time or '09:00:00'}")
			doc = frappe.get_doc({"doctype": "Pulse Meeting", "space": space.name, "scheduled_start": when})
			doc.flags.pulse_system = True
			doc.auto_generated = 1
			doc.insert(ignore_permissions=True)
		frappe.db.commit()


def daily_digest():
	"""One email per person who has something due within two days or overdue."""
	if not cint(settings().digest_enabled):
		return
	day = getdate(today())
	rows = frappe.get_all(
		"Pulse Action",
		filters={"status": "Open", "due_date": ["<=", add_days(day, 2)]},
		fields=["name", "title", "assigned_to", "due_date", "space"],
		order_by="due_date asc",
	)
	by_user = {}
	for r in rows:
		by_user.setdefault(r.assigned_to, []).append(r)
	for user in enabled_users(list(by_user)):
		items = by_user[user]
		frappe.sendmail(
			recipients=[user],
			subject=_("Your Pulse actions: {0} due or overdue").format(len(items)),
			template="pulse_digest",
			args={
				"overdue": [a for a in items if getdate(a.due_date) < day],
				"due": [a for a in items if getdate(a.due_date) >= day],
				"url": frappe.utils.get_url("/app/my-pulse"),
			},
			delayed=True,
		)


def unpublished_reminders():
	"""Concluded meetings whose summary was never sent: remind the facilitator, secretary and
	leaders each morning until it is published (or the meeting is cancelled)."""
	from bizhub_pulse.utils import space_leaders

	for m in frappe.get_all(
		"Pulse Meeting",
		filters={"status": "Concluded", "concluded_at": ["<", getdate(today())]},
		fields=["name", "title", "space", "facilitator", "secretary", "concluded_at"],
	):
		users = enabled_users(list(dict.fromkeys([u for u in (m.facilitator, m.secretary) if u] + space_leaders(m.space))))
		if not users:
			continue
		frappe.sendmail(
			recipients=users,
			subject=_("Not sent yet: summary and minutes of {0}").format(m.title),
			template="pulse_unpublished",
			args={"meeting": m, "url": frappe.utils.get_url(f"/app/pulse-room/{m.name}")},
			reference_doctype="Pulse Meeting",
			reference_name=m.name,
			delayed=True,
		)


def meeting_reminders():
	"""Remind attendees the day before. Each meeting is reminded once."""
	tomorrow = add_days(getdate(today()), 1)
	for name in frappe.get_all(
		"Pulse Meeting",
		filters={"status": "Scheduled", "reminder_sent": 0, "scheduled_start": ["between", [tomorrow, tomorrow]]},
		pluck="name",
	):
		doc = frappe.get_doc("Pulse Meeting", name)
		recipients = enabled_users([r.user for r in doc.attendees if r.attendance != "Excused"])
		if recipients:
			frappe.sendmail(
				recipients=recipients,
				subject=_("Tomorrow: {0}").format(doc.title),
				template="pulse_reminder",
				args={"meeting": doc, "url": frappe.utils.get_url(f"/app/pulse-room/{doc.name}")},
				reference_doctype="Pulse Meeting",
				reference_name=doc.name,
				delayed=True,
			)
		frappe.db.set_value("Pulse Meeting", name, "reminder_sent", 1, update_modified=False)
