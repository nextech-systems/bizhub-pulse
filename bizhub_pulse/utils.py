# Copyright (c) 2026, NextTech BizHub and contributors
# License: MIT. See LICENSE
"""Helpers shared by the Pulse controllers and API."""

import frappe
from frappe import _
from frappe.utils import add_days, cint, cstr, getdate, today

from bizhub_pulse import visibility


def _norm(value):
	if value in (None, "", 0, "0", 0.0):
		return ""
	return cstr(value)


def guard_protected(doc, fields):
	"""Refuse changes to system-managed fields unless the change comes from Pulse itself."""
	if doc.flags.pulse_system or frappe.flags.in_install or frappe.flags.in_migrate:
		return
	before = doc.get_doc_before_save()
	meta = doc.meta
	auto = (doc.flags.pulse_auto or set()) if before is None else set()
	for field in fields:
		if field in auto:
			continue
		if before is not None:
			old = before.get(field)
		else:
			df = meta.get_field(field)
			old = df.default if df else None
		if _norm(doc.get(field)) != _norm(old):
			label = meta.get_label(field)
			frappe.throw(_("{0} is set by BizHub Pulse and cannot be changed directly.").format(label), frappe.PermissionError)


def changed(doc, field):
	before = doc.get_doc_before_save()
	return before is not None and _norm(before.get(field)) != _norm(doc.get(field))


def check_space_change(doc, field="space", contribute=True):
	"""A record moved to (or created in) a space must be one the user can work in."""
	if doc.flags.pulse_system:
		return
	if doc.is_new() or changed(doc, field):
		space = doc.get(field)
		check = visibility.can_contribute if contribute else visibility.can_manage
		if space and not check(space):
			frappe.throw(_("You cannot add records to space {0}.").format(space), frappe.PermissionError)


def check_reference(doc):
	"""A linked ERPNext record must exist and be readable by the person linking it."""
	if not doc.get("reference_doctype") and not doc.get("reference_name"):
		return
	if not (doc.get("reference_doctype") and doc.get("reference_name")):
		frappe.throw(_("Choose both the linked DocType and the record."))
	if doc.flags.pulse_system or not (doc.is_new() or changed(doc, "reference_name") or changed(doc, "reference_doctype")):
		return
	if not frappe.db.exists(doc.reference_doctype, doc.reference_name):
		frappe.throw(_("{0} {1} does not exist.").format(doc.reference_doctype, doc.reference_name))
	if not frappe.has_permission(doc.reference_doctype, "read", doc.reference_name):
		frappe.throw(_("You cannot link a record you are not allowed to read."), frappe.PermissionError)


def settings():
	return frappe.get_cached_doc("Pulse Settings")


def default_due_date(base=None):
	days = cint(settings().default_due_days) or 7
	return add_days(getdate(base or today()), days)


def active_members(space, include_observers=True):
	filters = {"parent": space, "parenttype": "Pulse Space", "active": 1}
	if not include_observers:
		filters["member_role"] = ["!=", "Observer"]
	return frappe.get_all("Pulse Space Member", filters=filters, pluck="user", order_by="idx asc")


def enabled_users(users):
	users = [u for u in dict.fromkeys(users) if u and u not in ("Guest",)]
	if not users:
		return []
	enabled = set(frappe.get_all("User", filters={"name": ["in", users], "enabled": 1}, pluck="name"))
	return [u for u in users if u in enabled]


def space_leaders(space):
	return frappe.get_all(
		"Pulse Space Member",
		filters={"parent": space, "parenttype": "Pulse Space", "active": 1, "member_role": "Leader"},
		pluck="user",
	)
