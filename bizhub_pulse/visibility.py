# Copyright (c) 2026, NextTech BizHub and contributors
# License: MIT. See LICENSE
"""Who may see and change BizHub Pulse records.

Every decision about an existing record is made from the row stored in the
database, never from the document being submitted. Lists, counts, reports,
search and link fields use the same rules through permission_query_conditions.
"""

import frappe

ADMIN_ROLE = "Pulse Admin"
USER_ROLE = "Pulse User"
MANAGE_ROLES = ("Leader", "Facilitator", "Secretary")

PULSE_DOCTYPES = (
	"Pulse Space",
	"Pulse Meeting",
	"Pulse Meeting Notes",
	"Pulse Issue",
	"Pulse Decision",
	"Pulse Action",
	"Pulse Headline",
	"Pulse Message",
	"Pulse Priority",
)
READ_TYPES = ("read", "select", "print", "email", "report", "export")


# ---------------------------------------------------------------- lookups


def _cache():
	cache = getattr(frappe.local, "pulse_visibility", None)
	if cache is None:
		cache = frappe.local.pulse_visibility = {}
	return cache


def clear_cache(*args, **kwargs):
	frappe.local.pulse_visibility = {}


def _cached(key, fn):
	cache = _cache()
	if key not in cache:
		cache[key] = fn()
	return cache[key]


def is_admin(user=None):
	user = user or frappe.session.user
	return user == "Administrator" or ADMIN_ROLE in frappe.get_roles(user)


def memberships(user):
	"""{space: member_role} for active memberships in enabled spaces."""

	def load():
		rows = frappe.db.sql(
			"""select m.parent, m.member_role from `tabPulse Space Member` m
			join `tabPulse Space` s on s.name = m.parent
			where m.parenttype = 'Pulse Space' and m.parentfield = 'members'
				and m.user = %s and m.active = 1 and ifnull(s.disabled, 0) = 0""",
			(user,),
		)
		return {space: role for space, role in rows}

	return _cached(("memberships", user), load)


def _employee_tree():
	def load():
		rows = frappe.get_all(
			"Employee", filters={"status": "Active"}, fields=["name", "user_id", "reports_to"]
		)
		by_name = {r.name: r for r in rows}
		children = {}
		for r in rows:
			if r.reports_to:
				children.setdefault(r.reports_to, []).append(r.name)
		return by_name, children

	return _cached(("employees",), load)


def reports_of(user):
	"""Users who report to `user`, directly or indirectly."""

	def load():
		by_name, children = _employee_tree()
		start = [e.name for e in by_name.values() if e.user_id == user]
		seen, out, stack = set(start), set(), list(start)
		while stack:
			for child in children.get(stack.pop(), []):
				if child in seen:
					continue
				seen.add(child)
				stack.append(child)
				if by_name[child].user_id:
					out.add(by_name[child].user_id)
		out.discard(user)
		return out

	return _cached(("reports", user), load)


def _spaces():
	return _cached(
		("spaces",),
		lambda: {
			s.name: s
			for s in frappe.get_all(
				"Pulse Space",
				filters={"disabled": 0},
				fields=["name", "space_type", "visibility", "person_user"],
			)
		},
	)


def readable_spaces(user):
	"""Spaces whose content `user` may read (not counting Pulse Admin)."""

	def load():
		mine = set(memberships(user))
		reports = reports_of(user)
		for s in _spaces().values():
			if s.space_type == "Company":
				mine.add(s.name)
			elif s.space_type == "Person" and (s.person_user == user or s.person_user in reports):
				mine.add(s.name)
		return mine

	return _cached(("readable", user), load)


def listable_spaces(user):
	"""Spaces whose existence `user` may see: readable ones plus Private team/project spaces."""
	out = set(readable_spaces(user))
	for s in _spaces().values():
		if s.visibility == "Private" and s.space_type in ("Team", "Project"):
			out.add(s.name)
	return out


def manage_spaces(user):
	"""Spaces where `user` runs meetings and records decisions."""

	def load():
		out = {space for space, role in memberships(user).items() if role in MANAGE_ROLES}
		reports = reports_of(user)
		for s in _spaces().values():
			if s.space_type == "Person" and (s.person_user == user or s.person_user in reports):
				out.add(s.name)
		return out

	return _cached(("manage", user), load)


def leader_spaces(user):
	"""Spaces where `user` sees Restricted items: Leaders, and managers in Person spaces."""

	def load():
		out = {space for space, role in memberships(user).items() if role == "Leader"}
		reports = reports_of(user)
		for s in _spaces().values():
			if s.space_type == "Person" and s.person_user in reports:
				out.add(s.name)
		return out

	return _cached(("leader", user), load)


def contribute_spaces(user):
	"""Spaces where `user` may raise issues, add headlines and assign actions."""

	def load():
		out = {space for space, role in memberships(user).items() if role != "Observer"}
		return out | manage_spaces(user)

	return _cached(("contribute", user), load)


def can_read_space(space, user=None):
	user = user or frappe.session.user
	return is_admin(user) or space in readable_spaces(user)


def can_list_space(space, user=None):
	user = user or frappe.session.user
	return is_admin(user) or space in listable_spaces(user)


def can_manage(space, user=None):
	user = user or frappe.session.user
	return is_admin(user) or space in manage_spaces(user)


def can_contribute(space, user=None):
	user = user or frappe.session.user
	return is_admin(user) or space in contribute_spaces(user)


# ---------------------------------------------------------------- stored rows

STORED_FIELDS = {
	"Pulse Space": ["name", "space_type", "visibility", "person_user"],
	"Pulse Meeting": ["name", "space", "facilitator", "secretary"],
	"Pulse Meeting Notes": ["name", "meeting", "space"],
	"Pulse Issue": ["name", "space", "visibility", "issue_owner", "raised_by"],
	"Pulse Decision": ["name", "space", "meeting"],
	"Pulse Action": ["name", "space", "visibility", "assigned_to", "assigned_by"],
	"Pulse Headline": ["name", "space", "author"],
	"Pulse Message": ["name", "from_space"],
	"Pulse Priority": ["name", "space", "visibility", "priority_owner", "owner"],
}


def _is_new(doc):
	return bool(doc.get("__islocal")) or not doc.get("name") or not frappe.db.exists(doc.doctype, doc.name)


def _stored(doctype, name):
	return frappe.db.get_value(doctype, name, STORED_FIELDS[doctype], as_dict=True)


def _meeting_people(meeting):
	attendees = frappe.get_all(
		"Pulse Meeting Attendee",
		filters={"parent": meeting, "parenttype": "Pulse Meeting"},
		pluck="user",
	)
	recipients = frappe.get_all(
		"Pulse Publication",
		filters={"parent": meeting, "parenttype": "Pulse Meeting", "scope": "Full Summary"},
		pluck="user",
	)
	return set(attendees), set(recipients)


def _priority_contributors(name):
	return frappe.get_all(
		"Pulse Priority Contributor", filters={"parent": name, "parenttype": "Pulse Priority"}, pluck="user"
	)


def _message_targets(name):
	return frappe.get_all(
		"Pulse Message Target", filters={"parent": name, "parenttype": "Pulse Message"}, pluck="space"
	)


# ---------------------------------------------------------------- decisions


def can_read(doctype, row, user):
	"""Read access to a stored row (dict of STORED_FIELDS)."""
	if is_admin(user):
		return True
	if doctype == "Pulse Space":
		if row.name in readable_spaces(user):
			return True
		return row.visibility == "Private" and row.space_type in ("Team", "Project")
	if doctype == "Pulse Meeting":
		if row.space in readable_spaces(user) or user in (row.facilitator, row.secretary):
			return True
		attendees, recipients = _meeting_people(row.name)
		return user in attendees or user in recipients
	if doctype == "Pulse Meeting Notes":
		meeting = frappe.db.get_value("Pulse Meeting", row.meeting, ["space", "facilitator", "secretary"], as_dict=True)
		return bool(meeting) and (meeting.space in manage_spaces(user) or user in (meeting.facilitator, meeting.secretary))
	if doctype in ("Pulse Issue", "Pulse Action", "Pulse Priority"):
		owners = {
			"Pulse Issue": [row.get("issue_owner"), row.get("raised_by")],
			"Pulse Action": [row.get("assigned_to"), row.get("assigned_by")],
			"Pulse Priority": [row.get("priority_owner"), row.get("owner")],
		}[doctype]
		if doctype == "Pulse Priority" and user in _priority_contributors(row.name):
			return True
		if user in owners:
			return True
		if row.visibility == "Restricted":
			# Restricted: owners, the owners' managers (wherever they sit) and the space's leaders.
			return bool(set(owners) & reports_of(user)) or (
				row.space in readable_spaces(user) and row.space in leader_spaces(user)
			)
		return row.space in readable_spaces(user)
	if doctype in ("Pulse Decision", "Pulse Headline"):
		return row.space in readable_spaces(user)
	if doctype == "Pulse Message":
		readable = readable_spaces(user)
		return row.from_space in readable or any(t in readable for t in _message_targets(row.name))
	return False


def can_write(doctype, row, user):
	"""Change access to a stored row."""
	if is_admin(user):
		return True
	if doctype == "Pulse Space":
		return memberships(user).get(row.name) == "Leader"
	if doctype == "Pulse Meeting":
		return row.space in manage_spaces(user) or user in (row.facilitator, row.secretary)
	if doctype == "Pulse Meeting Notes":
		return can_read(doctype, row, user)
	if doctype == "Pulse Issue":
		return user in (row.issue_owner, row.raised_by) or row.space in manage_spaces(user)
	if doctype == "Pulse Action":
		# The owner may only change status, note and evidence (enforced in the controller).
		return user in (row.assigned_to, row.assigned_by) or row.space in manage_spaces(user)
	if doctype == "Pulse Decision":
		if row.space in manage_spaces(user):
			return True
		if row.meeting:
			m = frappe.db.get_value("Pulse Meeting", row.meeting, ["facilitator", "secretary"], as_dict=True)
			return bool(m) and user in (m.facilitator, m.secretary)
		return False
	if doctype == "Pulse Headline":
		return user == row.author or row.space in manage_spaces(user)
	if doctype == "Pulse Message":
		return row.from_space in manage_spaces(user)
	if doctype == "Pulse Priority":
		# The owner keeps it up to date (limited fields, enforced in the controller).
		return user == row.priority_owner or row.space in manage_spaces(user)
	return False


def can_create(doc, user):
	"""Create access, from the submitted document (there is no stored row yet)."""
	if is_admin(user):
		return True
	dt = doc.doctype
	if dt == "Pulse Space":
		return False
	if dt == "Pulse Meeting":
		return bool(doc.get("space")) and can_manage(doc.space, user)
	if dt == "Pulse Meeting Notes":
		m = frappe.db.get_value("Pulse Meeting", doc.get("meeting"), STORED_FIELDS["Pulse Meeting"], as_dict=True)
		return bool(m) and can_write("Pulse Meeting", m, user)
	if dt in ("Pulse Issue", "Pulse Action", "Pulse Headline"):
		return bool(doc.get("space")) and can_contribute(doc.space, user)
	if dt == "Pulse Decision":
		if doc.get("space") and can_manage(doc.space, user):
			return True
		m = doc.get("meeting") and frappe.db.get_value(
			"Pulse Meeting", doc.meeting, STORED_FIELDS["Pulse Meeting"], as_dict=True
		)
		return bool(m) and m.space == doc.get("space") and user in (m.facilitator, m.secretary)
	if dt == "Pulse Message":
		return bool(doc.get("from_space")) and can_manage(doc.from_space, user)
	if dt == "Pulse Priority":
		return bool(doc.get("space")) and can_manage(doc.space, user)
	return False


def has_permission(doc, ptype=None, user=None, debug=False):
	"""has_permission hook for every Pulse DocType. Always returns True or False."""
	user = user or frappe.session.user
	ptype = ptype or "read"
	if ptype == "share":
		return False
	if is_admin(user):
		return True
	if ptype == "create" or _is_new(doc):
		if ptype in READ_TYPES:
			return True  # an unsaved form the user is filling in
		return can_create(doc, user)
	row = _stored(doc.doctype, doc.name)
	if not row:
		return False
	if ptype in READ_TYPES:
		return can_read(doc.doctype, row, user)
	if ptype == "delete":
		return False
	return can_read(doc.doctype, row, user) and can_write(doc.doctype, row, user)


# ---------------------------------------------------------------- list conditions


def _in(values):
	values = [v for v in values if v]
	if not values:
		return "('')"
	return "(" + ", ".join(frappe.db.escape(v) for v in sorted(values)) + ")"


def _user(user):
	return user or frappe.session.user


def space_conditions(user=None):
	user = _user(user)
	if is_admin(user):
		return ""
	return f"`tabPulse Space`.`name` in {_in(listable_spaces(user))}"


def meeting_conditions(user=None):
	user = _user(user)
	if is_admin(user):
		return ""
	u = frappe.db.escape(user)
	t = "`tabPulse Meeting`"
	return (
		f"({t}.`space` in {_in(readable_spaces(user))} or {t}.`facilitator` = {u} or {t}.`secretary` = {u}"
		f" or {t}.`name` in (select `parent` from `tabPulse Meeting Attendee` where `parenttype` = 'Pulse Meeting' and `user` = {u})"
		f" or {t}.`name` in (select `parent` from `tabPulse Publication` where `parenttype` = 'Pulse Meeting'"
		f" and `scope` = 'Full Summary' and `user` = {u}))"
	)


def notes_conditions(user=None):
	user = _user(user)
	if is_admin(user):
		return ""
	u = frappe.db.escape(user)
	t = "`tabPulse Meeting Notes`"
	return (
		f"({t}.`space` in {_in(manage_spaces(user))} or {t}.`meeting` in"
		f" (select `name` from `tabPulse Meeting` where `facilitator` = {u} or `secretary` = {u}))"
	)


def _owned_conditions(table, owner_fields, user):
	if is_admin(user):
		return ""
	u = frappe.db.escape(user)
	t = f"`tab{table}`"
	owners = " or ".join(f"{t}.`{f}` = {u}" for f in owner_fields)
	reports = _in(reports_of(user))
	managers_see = " or ".join(f"{t}.`{f}` in {reports}" for f in owner_fields)
	readable = _in(readable_spaces(user))
	return (
		f"({owners} or (ifnull({t}.`visibility`, 'Team') != 'Restricted' and {t}.`space` in {readable})"
		f" or (ifnull({t}.`visibility`, 'Team') = 'Restricted' and ({managers_see}"
		f" or ({t}.`space` in {readable} and {t}.`space` in {_in(leader_spaces(user))}))))"
	)


def issue_conditions(user=None):
	return _owned_conditions("Pulse Issue", ("issue_owner", "raised_by"), _user(user))


def action_conditions(user=None):
	return _owned_conditions("Pulse Action", ("assigned_to", "assigned_by"), _user(user))


def priority_conditions(user=None):
	user = _user(user)
	base = _owned_conditions("Pulse Priority", ("priority_owner", "owner"), user)
	if not base:
		return ""
	u = frappe.db.escape(user)
	return (
		f"({base} or `tabPulse Priority`.`name` in (select `parent` from `tabPulse Priority Contributor`"
		f" where `parenttype` = 'Pulse Priority' and `user` = {u}))"
	)


def _space_only(table, field="space"):
	def conditions(user=None):
		user = _user(user)
		if is_admin(user):
			return ""
		return f"`tab{table}`.`{field}` in {_in(readable_spaces(user))}"

	return conditions


decision_conditions = _space_only("Pulse Decision")
headline_conditions = _space_only("Pulse Headline")


def message_conditions(user=None):
	user = _user(user)
	if is_admin(user):
		return ""
	readable = _in(readable_spaces(user))
	t = "`tabPulse Message`"
	return (
		f"({t}.`from_space` in {readable} or {t}.`name` in (select `parent` from `tabPulse Message Target`"
		f" where `parenttype` = 'Pulse Message' and `space` in {readable}))"
	)


# ---------------------------------------------------------------- history and comments
# Frappe stores change history (Version) and comments (Comment) as their own
# records, which System Managers can list. Rows about a Pulse record follow
# that record's own read rule; every other row is left to Frappe.

_TABLE_CONDITIONS = {
	"Pulse Space": "space_conditions",
	"Pulse Meeting": "meeting_conditions",
	"Pulse Meeting Notes": "notes_conditions",
	"Pulse Issue": "issue_conditions",
	"Pulse Decision": "decision_conditions",
	"Pulse Action": "action_conditions",
	"Pulse Headline": "headline_conditions",
	"Pulse Message": "message_conditions",
	"Pulse Priority": "priority_conditions",
}


def _linked_conditions(table, dt_field, name_field, user):
	user = _user(user)
	if is_admin(user):
		return ""
	t = f"`tab{table}`"
	parts = [f"ifnull({t}.`{dt_field}`, '') not in {_in(PULSE_DOCTYPES)}"]
	for doctype in PULSE_DOCTYPES:
		cond = globals()[_TABLE_CONDITIONS[doctype]](user)
		sub = f"select `name` from `tab{doctype}`" + (f" where {cond}" if cond else "")
		parts.append(f"({t}.`{dt_field}` = {frappe.db.escape(doctype)} and {t}.`{name_field}` in ({sub}))")
	return "(" + " or ".join(parts) + ")"


def version_conditions(user=None):
	return _linked_conditions("Version", "ref_doctype", "docname", user)


def comment_conditions(user=None):
	return _linked_conditions("Comment", "reference_doctype", "reference_name", user)


def _linked_permission(ref_doctype, ref_name, user):
	if ref_doctype not in PULSE_DOCTYPES:
		return None  # not ours: Frappe (and other apps) decide
	if not ref_name or not frappe.db.exists(ref_doctype, ref_name):
		return False
	return frappe.has_permission(ref_doctype, "read", doc=str(ref_name), user=user)


def version_has_permission(doc, ptype=None, user=None, debug=False):
	return _linked_permission(doc.get("ref_doctype"), doc.get("docname"), user or frappe.session.user)


def comment_has_permission(doc, ptype=None, user=None, debug=False):
	return _linked_permission(doc.get("reference_doctype"), doc.get("reference_name"), user or frappe.session.user)


# ---------------------------------------------------------------- sharing


def block_share(doc, method=None):
	"""Pulse records are reached through space membership, never through shares."""
	if doc.share_doctype in PULSE_DOCTYPES:
		frappe.throw(
			frappe._("BizHub Pulse records are shared through space membership, not document sharing."),
			frappe.PermissionError,
		)
