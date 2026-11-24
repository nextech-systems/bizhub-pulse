# Copyright (c) 2026, NextTech BizHub and contributors
# License: MIT. See LICENSE
"""Roles, starter templates and settings. Existing records are never overwritten."""

import json

import frappe

GUARDED = ("Version", "Comment", "*")
ROLES = ("Pulse User", "Pulse Admin", "BizPulse Meeting Host")

TEMPLATES = {
	"Weekly Team Meeting": [
		("Opening", "Good news", 5, "One piece of personal or business good news from each person."),
		("Scorecard", "Scorecard", 5, "Numbers on or off track. Off-track numbers go to Issues, no discussion here."),
		("Priorities", "Priorities", 5, "Each owner: on track or off track. Off track goes to Issues, no discussion here."),
		("Headlines", "Headlines", 5, "Customer and staff news, and messages from other teams. Discussion goes to Issues."),
		("Action Review", "Action review", 5, "Done or not done. Not done goes to next week or to Issues."),
		("Issue Solving", "Issue solving", 60, "Pick the top three. Identify the real cause, discuss, decide, assign actions."),
		("Conclusion", "Conclusion", 5, "Recap new actions and messages. Rate the meeting if you like."),
	],
	"Weekly Leadership Meeting": [
		("Opening", "Good news", 5, "One piece of personal or business good news from each person."),
		("Scorecard", "Company scorecard", 5, "Company-level numbers on or off track."),
		("Priorities", "Priorities", 5, "Company and team priorities: on track or off track."),
		("Headlines", "Headlines", 5, "Customer and staff news, and messages from teams."),
		("Action Review", "Action review", 5, "Done or not done."),
		("Issue Solving", "Issue solving", 60, "Most important issues first. Decide, assign, cascade."),
		("Conclusion", "Conclusion", 5, "Recap actions, approve messages to teams, rate the meeting."),
	],
	"Daily Huddle": [
		("Headlines", "Today", 5, "What matters today: deliveries, absences, priorities."),
		("Action Review", "Yesterday's actions", 5, "Done or not done."),
		("Issue Solving", "Stuck points", 5, "Name what is blocking work; solve quickly or take it to the weekly meeting."),
	],
}

LINKABLE = ("Sales Order", "Delivery Note", "Work Order", "Customer", "Purchase Order")


def after_install():
	ensure_defaults(first_install=True)
	keep_guard_order()


def after_migrate():
	ensure_defaults()
	keep_guard_order()


def keep_guard_order():
	"""Let other apps' Version/Comment permission hooks run before Pulse's.

	Frappe asks has_permission hooks newest-installed app first and stops at the
	first answer. Pulse's Version and Comment hooks answer only for Pulse records
	and pass everything else through, so their position changes no outcome; but
	an app such as todo_privacy checks that its own hook is asked first.
	Pulse therefore sits just before the earliest app that also guards Version
	or Comment.
	"""
	apps = list(frappe.get_installed_apps())
	if "bizhub_pulse" not in apps:
		return
	guards = []
	for app in apps:
		if app == "bizhub_pulse":
			continue
		hooks = frappe.get_hooks("has_permission", {}, app_name=app) or {}
		if any(dt in hooks for dt in GUARDED):
			guards.append(apps.index(app))
	if not guards or apps.index("bizhub_pulse") < min(guards):
		return
	# Never ahead of the apps Pulse needs.
	required = [apps.index(a) for a in ("frappe", "erpnext") if a in apps]
	target = min(guards)
	if required and max(required) >= target:
		frappe.log_error(
			"BizHub Pulse install order",
			"Another app guards Version/Comment but is installed before ERPNext; Pulse left in place.",
		)
		return
	apps.remove("bizhub_pulse")
	apps.insert(target, "bizhub_pulse")
	frappe.db.set_global("installed_apps", json.dumps(apps))
	frappe.db.commit()
	frappe.clear_cache()


def ensure_defaults(first_install=False):
	for role in ROLES:
		if not frappe.db.exists("Role", role):
			frappe.get_doc({"doctype": "Role", "role_name": role, "desk_access": 1}).insert(ignore_permissions=True)
	for name, sections in TEMPLATES.items():
		if frappe.db.exists("Pulse Meeting Template", name):
			continue
		frappe.get_doc(
			{
				"doctype": "Pulse Meeting Template",
				"template_name": name,
				"sections": [
					{"section_type": t, "title": title, "minutes": m, "guidance": g} for t, title, m, g in sections
				],
			}
		).insert(ignore_permissions=True)
	s = frappe.get_single("Pulse Settings")
	changed = False
	if not s.default_due_days:
		s.default_due_days = 7
		changed = True
	if first_install and not s.linkable_doctypes:
		# Only on first install: an admin who later empties the list keeps it empty.
		for dt in LINKABLE:
			if frappe.db.exists("DocType", dt):
				s.append("linkable_doctypes", {"document_type": dt})
		changed = True
	if changed:
		s.flags.ignore_permissions = True
		s.save()
	frappe.db.commit()


def boot_session(bootinfo):
	roles = frappe.get_roles()
	if "Pulse User" not in roles and "Pulse Admin" not in roles:
		return
	bootinfo.pulse_linkable = frappe.get_all(
		"Pulse Linkable DocType", filters={"parent": "Pulse Settings"}, pluck="document_type"
	)
