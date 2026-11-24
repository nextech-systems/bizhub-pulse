# Copyright (c) 2026, NextTech BizHub and contributors
# License: MIT. See LICENSE
"""Whitelisted methods behind the meeting screen and My Pulse.

Every method checks access first. Records are created and saved with the
caller's own permissions; `ignore_permissions` is used only for changes Pulse
makes itself after the caller has been checked (marked with flags.pulse_system).
"""

import json

import frappe
from frappe import _
from frappe.utils import add_days, cint, escape_html, get_datetime, getdate, now_datetime, today
from frappe.utils.html_utils import sanitize_html

from bizhub_pulse import visibility
from bizhub_pulse.utils import active_members, default_due_date, enabled_users, settings, space_leaders

# ---------------------------------------------------------------- helpers


def _loads(value):
	if isinstance(value, str):
		return json.loads(value) if value else []
	return value or []


def _meeting(name, ptype="read", lock=False):
	"""Load a meeting and check access. lock=True waits for any other change to the
	same meeting to finish first (row lock), so simultaneous saves from the meeting
	screen, such as the section timer and the minutes, never collide."""
	if lock:
		frappe.db.sql("select name from `tabPulse Meeting` where name = %s for update", (name,))
	doc = frappe.get_doc("Pulse Meeting", name)
	doc.check_permission(ptype)
	return doc


def _can_run(meeting):
	user = frappe.session.user
	return visibility.can_manage(meeting.space, user) or user in (meeting.facilitator, meeting.secretary)


def _require_run(meeting):
	if not _can_run(meeting):
		frappe.throw(_("Only the facilitator, secretary or a space leader can run this meeting."), frappe.PermissionError)


def _require_status(meeting, *statuses):
	if meeting.status not in statuses:
		frappe.throw(_("This meeting is {0}.").format(_(meeting.status)))


def _system_save(doc):
	doc.flags.pulse_system = True
	doc.save(ignore_permissions=True)
	return doc


def _since(meeting):
	if meeting.previous_meeting:
		prev = frappe.db.get_value("Pulse Meeting", meeting.previous_meeting, "scheduled_start")
		if prev:
			return getdate(prev)
	return add_days(getdate(meeting.scheduled_start), -7)


ACTION_FIELDS = [
	"name", "title", "assigned_to", "assigned_by", "due_date", "status", "visibility", "carried_over",
	"completed_on", "completion_note", "evidence_required", "evidence", "verified_by", "reviewed_in",
	"source_meeting", "issue", "decision", "reference_doctype", "reference_name",
]
ISSUE_FIELDS = [
	"name", "title", "issue_owner", "raised_by", "rank", "status", "visibility", "details", "discussion",
	"resolution", "reference_doctype", "reference_name", "raised_in", "solved_in",
]


# ---------------------------------------------------------------- meeting state


@frappe.whitelist()
def get_meeting(meeting):
	"""Everything the meeting screen shows, filtered by the caller's permissions."""
	doc = _meeting(meeting)
	day = getdate(doc.scheduled_start)
	since = _since(doc)
	space = doc.space

	review = frappe.get_list(
		"Pulse Action",
		filters={"space": space, "status": ["!=", "Cancelled"]},
		or_filters=None,
		fields=ACTION_FIELDS,
		order_by="due_date asc",
		limit_page_length=0,
	)
	to_review = [
		a for a in review
		if (a.reviewed_in == doc.name) or (not a.reviewed_in and a.status in ("Open", "Done", "Not Done") and getdate(a.due_date) <= day and a.source_meeting != doc.name)
	]
	done_early = [
		a for a in review
		if a.status == "Done" and a.completed_on and getdate(a.completed_on) >= since and getdate(a.due_date) > day
	]
	new_actions = [a for a in review if a.source_meeting == doc.name]

	issues = frappe.get_list(
		"Pulse Issue",
		filters={"space": space, "status": "Open"},
		fields=ISSUE_FIELDS,
		order_by="`rank` asc, creation asc",
		limit_page_length=0,
	)
	closed_here = frappe.get_list(
		"Pulse Issue",
		filters={"solved_in": doc.name},
		fields=ISSUE_FIELDS + ["escalated_to"],
		limit_page_length=0,
	)
	headlines = frappe.get_list(
		"Pulse Headline",
		filters={"space": space},
		or_filters=[["meeting", "=", doc.name], ["creation", ">=", since]],
		fields=["name", "headline", "kind", "author", "meeting"],
		order_by="creation asc",
		limit_page_length=0,
	)
	incoming = frappe.get_list(
		"Pulse Message",
		filters=[["status", "=", "Sent"], ["Pulse Message Target", "space", "=", space]],
		fields=["name", "message", "from_space", "sent_at"],
		order_by="sent_at desc",
		limit_page_length=50,
	)
	acknowledged = {
		r.parent: r.acknowledged_in
		for r in frappe.get_all(
			"Pulse Message Target",
			filters={"parenttype": "Pulse Message", "space": space, "parent": ["in", [m.name for m in incoming] or [""]]},
			fields=["parent", "acknowledged_in"],
		)
	}
	incoming = [m for m in incoming if acknowledged.get(m.name) in (None, "", doc.name)]
	for m in incoming:
		m.acknowledged_in = acknowledged.get(m.name)
	decisions = frappe.get_list(
		"Pulse Decision",
		filters={"meeting": doc.name},
		fields=["name", "decision", "reason", "issue", "status", "review_date", "publish", "approved_by"],
		order_by="creation asc",
		limit_page_length=0,
	)
	outgoing = frappe.get_list(
		"Pulse Message",
		filters={"from_meeting": doc.name},
		fields=["name", "message", "status", "communicator"],
		limit_page_length=0,
	)
	for m in outgoing:
		m.targets = frappe.get_all("Pulse Message Target", filters={"parent": m.name, "parenttype": "Pulse Message"}, pluck="space")

	user = frappe.session.user
	return {
		"meeting": doc.as_dict(),
		"priorities": _priorities(space),
		"space": frappe.db.get_value("Pulse Space", space, ["name", "space_type", "visibility"], as_dict=True),
		"to_review": to_review,
		"done_early": done_early,
		"new_actions": new_actions,
		"issues": issues,
		"closed_issues": closed_here,
		"headlines": headlines,
		"incoming_messages": incoming,
		"decisions": decisions,
		"outgoing_messages": outgoing,
		"members": active_members(space),
		"can_run": _can_run(doc),
		"dictation": _dictation(doc.name),
		"can_contribute": visibility.can_contribute(space, user),
		"is_attendee": any(r.user == user for r in doc.attendees),
		"default_due": str(default_due_date(day)),
		"server_time": str(now_datetime()),
	}


PRIORITY_FIELDS = [
	"name", "title", "priority_owner", "status", "kind", "quarter", "due_date", "visibility", "success_criteria",
	"measure_name", "unit", "start_value", "target_value", "current_value", "current_as_of", "support_needed",
]


def _priorities(space, include_closed=False):
	"""Open priorities of a space the caller may read, with milestones and linked open actions."""
	filters = {"space": space}
	if not include_closed:
		filters["status"] = ["in", ["On Track", "Off Track"]]
	rows = frappe.get_list("Pulse Priority", filters=filters, fields=PRIORITY_FIELDS, order_by="due_date asc", limit_page_length=0)
	names = [r.name for r in rows] or [""]
	milestones = frappe.get_all(
		"Pulse Priority Milestone",
		filters={"parent": ["in", names], "parenttype": "Pulse Priority"},
		fields=["parent", "idx", "milestone", "milestone_owner", "due_date", "done", "done_on"],
		order_by="idx asc",
	)
	open_actions = frappe.get_list(
		"Pulse Action",
		filters={"priority": ["in", names], "status": "Open"},
		fields=["name", "priority", "title", "assigned_to", "due_date"],
		order_by="due_date asc",
		limit_page_length=0,
	)
	day = getdate(today())
	for r in rows:
		r.milestones = [m for m in milestones if m.parent == r.name]
		r.open_actions = [a for a in open_actions if a.priority == r.name]
		r.next_milestone = next((m for m in r.milestones if not m.done), None)
		r.milestones_done = sum(1 for m in r.milestones if m.done)
		r.overdue = [m.milestone for m in r.milestones if not m.done and getdate(m.due_date) < day]
	return rows


@frappe.whitelist()
def update_priority(priority, status=None, current_value=None, support_needed=None, dependencies=None):
	"""The owner (or a leader) reports progress. What was agreed is changed on the form by a leader."""
	doc = frappe.get_doc("Pulse Priority", priority)
	doc.check_permission("write")
	if status:
		if status not in ("On Track", "Off Track", "Done", "Dropped"):
			frappe.throw(_("Unknown status."))
		if status == "Dropped" and not visibility.can_manage(doc.space):
			frappe.throw(_("Only a space leader can drop a priority."), frappe.PermissionError)
		doc.status = status
	if current_value not in (None, ""):
		doc.current_value = float(current_value)
	if support_needed is not None:
		doc.support_needed = support_needed
	if dependencies is not None:
		doc.dependencies = dependencies
	doc.save()
	return doc.as_dict()


@frappe.whitelist()
def set_milestone(priority, idx, done):
	doc = frappe.get_doc("Pulse Priority", priority)
	doc.check_permission("read")
	row = next((r for r in doc.milestones if r.idx == cint(idx)), None)
	if not row:
		frappe.throw(_("No such milestone."))
	user = frappe.session.user
	if not (user in (doc.priority_owner, row.milestone_owner) or visibility.can_manage(doc.space, user)):
		frappe.throw(_("Only the priority's owner, the milestone's owner or a space leader can tick it."), frappe.PermissionError)
	row.done = cint(done)
	_system_save(doc)  # access checked above; the controller still recalculates on/off track
	return doc.as_dict()


# ---------------------------------------------------------------- running the meeting


def _close_current_section(doc, now):
	idx = cint(doc.current_section)
	if 0 < idx <= len(doc.sections):
		row = doc.sections[idx - 1]
		if row.started_at:
			row.actual_seconds = cint(row.actual_seconds) + int((now - get_datetime(row.started_at)).total_seconds())
			row.started_at = None


@frappe.whitelist()
def start_meeting(meeting):
	doc = _meeting(meeting, lock=True)
	_require_run(doc)
	_require_status(doc, "Scheduled")
	now = now_datetime()
	doc.status = "In Progress"
	doc.started_at = now
	if doc.sections:
		doc.current_section = 1
		doc.sections[0].started_at = now
	for row in doc.attendees:
		if row.attendance in (None, "", "Expected"):
			row.attendance = "Present"
	_system_save(doc)
	return get_meeting(meeting)


@frappe.whitelist()
def goto_section(meeting, index):
	doc = _meeting(meeting, lock=True)
	_require_run(doc)
	_require_status(doc, "In Progress")
	index = cint(index)
	if not 1 <= index <= len(doc.sections):
		frappe.throw(_("No such section."))
	now = now_datetime()
	_close_current_section(doc, now)
	doc.current_section = index
	doc.sections[index - 1].started_at = now
	_system_save(doc)
	return {"current_section": index, "sections": [r.as_dict() for r in doc.sections]}


@frappe.whitelist()
def conclude_meeting(meeting):
	doc = _meeting(meeting, lock=True)
	_require_run(doc)
	_require_status(doc, "In Progress")
	now = now_datetime()
	_close_current_section(doc, now)
	doc.status = "Concluded"
	doc.concluded_at = now
	_system_save(doc)
	return get_meeting(meeting)


@frappe.whitelist()
def cancel_meeting(meeting):
	doc = _meeting(meeting, lock=True)
	_require_run(doc)
	_require_status(doc, "Scheduled")
	doc.status = "Cancelled"
	_system_save(doc)
	return {"status": doc.status}


@frappe.whitelist()
def set_attendance(meeting, user, attendance):
	doc = _meeting(meeting, lock=True)
	_require_run(doc)
	_require_status(doc, "Scheduled", "In Progress", "Concluded")
	if attendance not in ("Expected", "Present", "Absent", "Excused"):
		frappe.throw(_("Unknown attendance."))
	row = next((r for r in doc.attendees if r.user == user), None)
	if not row:
		if not frappe.db.get_value("User", user, "enabled"):
			frappe.throw(_("{0} is not an active user.").format(user))
		row = doc.append("attendees", {"user": user, "attendance": "Expected"})
	row.attendance = attendance
	_system_save(doc)
	return {"ok": True}


@frappe.whitelist()
def set_rating(meeting, rating=None):
	"""An attendee rates the meeting (optional, 1 to 10). Only their own row."""
	doc = _meeting(meeting, lock=True)
	_require_status(doc, "In Progress", "Concluded")
	row = next((r for r in doc.attendees if r.user == frappe.session.user), None)
	if not row:
		frappe.throw(_("Only attendees can rate a meeting."), frappe.PermissionError)
	rating = cint(rating) or None
	if rating and not 1 <= rating <= 10:
		frappe.throw(_("Ratings are from 1 to 10."))
	row.rating = rating
	_system_save(doc)
	return {"average_rating": doc.average_rating}


DICTATION_TTL = 150  # seconds; the dictating browser renews every minute


def _dictation(name):
	return frappe.cache().get_value(f"pulse_dictation|{name}", expires=True)


@frappe.whitelist(methods=["POST"])
def set_dictation(meeting, on=1):
	"""The facilitator or secretary turns dictation on or off. Everyone on the meeting screen is told,
	so nobody is transcribed without knowing it. The browser renews the flag while dictating."""
	doc = _meeting(meeting)
	_require_run(doc)
	key = f"pulse_dictation|{doc.name}"
	current = _dictation(doc.name)
	user = frappe.session.user
	if cint(on):
		if current and current.get("by") != user:
			frappe.throw(_("{0} is already dictating in this meeting.").format(current.get("by_name")))
		state = {"by": user, "by_name": frappe.utils.get_fullname(user)}
		frappe.cache().set_value(key, state, expires_in_sec=DICTATION_TTL)
		changed = not current
	else:
		if current and current.get("by") != user and not visibility.is_admin(user):
			frappe.throw(_("Only {0} can stop their dictation.").format(current.get("by_name")))
		frappe.cache().delete_value(key)
		state, changed = None, bool(current)
	if changed:
		frappe.publish_realtime(
			"pulse_dictation", {"meeting": doc.name, "state": state}, doctype="Pulse Meeting", docname=doc.name, after_commit=True
		)
	return state


TANGENT_USER_GAP = 15  # seconds between two tangents from the same person
TANGENT_MEETING_GAP = 5  # seconds in which a second tangent from anyone is folded into the first


@frappe.whitelist(methods=["POST"])
def call_tangent(meeting):
	"""Anyone who can read a running meeting flags that the discussion has gone off topic.
	Everyone with the meeting screen open sees the alert; the count goes in the summary."""
	doc = _meeting(meeting)
	_require_status(doc, "In Progress")
	user = frappe.session.user
	cache = frappe.cache()
	user_key = f"pulse_tangent|{doc.name}|{user}"
	meeting_key = f"pulse_tangent|{doc.name}"
	if cache.get_value(user_key, expires=True):
		return {"sent": False, "reason": "wait", "tangent_count": cint(doc.tangent_count)}
	cache.set_value(user_key, 1, expires_in_sec=TANGENT_USER_GAP)
	if cache.get_value(meeting_key, expires=True):
		return {"sent": False, "reason": "already", "tangent_count": cint(doc.tangent_count)}
	cache.set_value(meeting_key, 1, expires_in_sec=TANGENT_MEETING_GAP)
	frappe.db.sql(
		"update `tabPulse Meeting` set tangent_count = ifnull(tangent_count, 0) + 1 where name = %s", (doc.name,)
	)
	count = cint(frappe.db.get_value("Pulse Meeting", doc.name, "tangent_count"))
	section = doc.sections[doc.current_section - 1].title if doc.current_section and doc.current_section <= len(doc.sections) else ""
	frappe.publish_realtime(
		"pulse_tangent",
		{"meeting": doc.name, "by": user, "by_name": frappe.utils.get_fullname(user), "section": section, "count": count},
		doctype="Pulse Meeting",
		docname=doc.name,
		after_commit=True,
	)
	return {"sent": True, "tangent_count": count, "section": section}


# ---------------------------------------------------------------- minutes and follow-up


@frappe.whitelist()
def save_minute(meeting, topic, minutes=None, issue=None):
	"""Save the minutes for one topic. The facilitator, secretary or a leader writes them until publishing."""
	doc = _meeting(meeting, lock=True)
	_require_run(doc)
	_require_status(doc, "Scheduled", "In Progress", "Concluded")
	topic = (topic or "").strip()[:140]
	if not topic:
		frappe.throw(_("Give the topic a name."))
	if issue and frappe.db.get_value("Pulse Issue", issue, "space") != doc.space:
		frappe.throw(_("The issue belongs to another space."))
	row = next((r for r in doc.minutes if r.topic == topic), None)
	if not row:
		row = doc.append("minutes", {"topic": topic})
	row.minutes = minutes or ""
	if issue:
		row.issue = issue
	_system_save(doc)
	return [r.as_dict() for r in doc.minutes]


@frappe.whitelist()
def meeting_followup(meeting):
	"""Live progress on everything a meeting produced, filtered by what the caller may see."""
	doc = _meeting(meeting)
	day = getdate(today())
	actions = frappe.get_list(
		"Pulse Action",
		filters={"source_meeting": doc.name},
		fields=["name", "title", "assigned_to", "due_date", "status", "visibility", "completed_on", "verified_by",
			"carried_over", "priority", "issue"],
		order_by="due_date asc",
		limit_page_length=0,
	)
	for a in actions:
		a.overdue = a.status == "Open" and getdate(a.due_date) < day
		a.owner_name = _user_label(a.assigned_to)
	issues = frappe.get_list(
		"Pulse Issue",
		filters=[["space", "=", doc.space]],
		or_filters=[["raised_in", "=", doc.name], ["solved_in", "=", doc.name]],
		fields=["name", "title", "status", "issue_owner", "raised_in", "solved_in", "escalated_to", "closed_on"],
		order_by="`rank` asc",
		limit_page_length=0,
	)
	for i in issues:
		i.owner_name = _user_label(i.issue_owner) if i.issue_owner else ""
	decisions = frappe.get_list(
		"Pulse Decision",
		filters={"meeting": doc.name},
		fields=["name", "decision", "status", "review_date", "superseded_by"],
		order_by="creation asc",
		limit_page_length=0,
	)
	stats = {
		"actions": len(actions),
		"done": sum(1 for a in actions if a.status == "Done"),
		"verified": sum(1 for a in actions if a.verified_by),
		"open": sum(1 for a in actions if a.status == "Open"),
		"overdue": sum(1 for a in actions if a.overdue),
		"not_done": sum(1 for a in actions if a.status == "Not Done"),
		"issues": len(issues),
		"issues_open": sum(1 for i in issues if i.status == "Open"),
	}
	return {"stats": stats, "actions": actions, "issues": issues, "decisions": decisions,
		"minutes": [r.as_dict() for r in doc.minutes], "status": doc.status}


# ---------------------------------------------------------------- actions


@frappe.whitelist()
def add_action(space, title, assigned_to, due_date=None, meeting=None, issue=None, decision=None, details=None, priority=None,
	visibility_=None, evidence_required=0, reference_doctype=None, reference_name=None, **kwargs):
	doc = frappe.get_doc(
		{
			"doctype": "Pulse Action",
			"space": space,
			"title": title,
			"assigned_to": assigned_to,
			"due_date": due_date or default_due_date(),
			"issue": issue,
			"decision": decision,
			"priority": priority,
			"details": details,
			"visibility": kwargs.get("visibility") or visibility_ or "Team",
			"evidence_required": cint(evidence_required),
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
		}
	)
	doc.insert()
	if meeting:
		m = _meeting(meeting)
		if m.space != doc.space:
			frappe.throw(_("The meeting belongs to another space."))
		doc.source_meeting = m.name
		_system_save(doc)
	return doc.as_dict()


@frappe.whitelist()
def review_action(action, meeting, result):
	"""Action review in a meeting: Done, Not Done, Carry (to next week) or Issue."""
	m = _meeting(meeting)
	_require_run(m)
	_require_status(m, "In Progress")
	doc = frappe.get_doc("Pulse Action", action)
	doc.check_permission("read")
	if doc.space != m.space:
		frappe.throw(_("This action belongs to another space."))
	out = {}
	if result == "Done":
		if doc.evidence_required and not (doc.completion_note or doc.evidence):
			frappe.throw(_("This action needs a completion note or evidence first."))
		doc.status = "Done"
		doc.reviewed_in = m.name
	elif result == "Not Done":
		doc.status = "Not Done"
		doc.reviewed_in = m.name
	elif result == "Carry":
		doc.status = "Open"
		doc.carried_over = cint(doc.carried_over) + 1
		doc.due_date = default_due_date(getdate(m.scheduled_start))
		doc.reviewed_in = None
	elif result == "Issue":
		doc.status = "Not Done"
		doc.reviewed_in = m.name
		issue = frappe.get_doc(
			{
				"doctype": "Pulse Issue",
				"space": m.space,
				"title": _("Not done: {0}").format(doc.title)[:140],
				"issue_owner": doc.assigned_to,
				"visibility": doc.visibility,
				"reference_doctype": doc.reference_doctype,
				"reference_name": doc.reference_name,
				"details": escape_html(doc.details or ""),
			}
		)
		issue.insert()
		issue.raised_in = m.name
		_system_save(issue)
		out["issue"] = issue.name
	else:
		frappe.throw(_("Unknown result."))
	_system_save(doc)
	out["action"] = doc.as_dict()
	return out


@frappe.whitelist()
def complete_action(action, completion_note=None):
	"""The owner marks their own action done between meetings."""
	doc = frappe.get_doc("Pulse Action", action)
	doc.check_permission("write")
	doc.status = "Done"
	if completion_note:
		doc.completion_note = completion_note
	doc.save()
	return doc.as_dict()


@frappe.whitelist()
def verify_action(action):
	"""The assigner (or a space leader) confirms the work was really done."""
	doc = frappe.get_doc("Pulse Action", action)
	doc.check_permission("read")
	user = frappe.session.user
	if not (user == doc.assigned_by or visibility.can_manage(doc.space, user)):
		frappe.throw(_("Only the person who assigned this action or a space leader can verify it."), frappe.PermissionError)
	if doc.status != "Done":
		frappe.throw(_("Only a Done action can be verified."))
	doc.verified_by = user
	doc.verified_on = now_datetime()
	_system_save(doc)
	return doc.as_dict()


# ---------------------------------------------------------------- issues and decisions


@frappe.whitelist()
def add_issue(space, title, details=None, meeting=None, issue_owner=None, visibility_=None,
	reference_doctype=None, reference_name=None, priority=None, **kwargs):
	doc = frappe.get_doc(
		{
			"doctype": "Pulse Issue",
			"space": space,
			"title": title,
			"details": details,
			"issue_owner": issue_owner,
			"priority": priority,
			"visibility": kwargs.get("visibility") or visibility_ or "Team",
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
		}
	)
	doc.insert()
	if meeting:
		m = _meeting(meeting)
		if m.space == doc.space:
			doc.raised_in = m.name
			_system_save(doc)
	return doc.as_dict()


@frappe.whitelist()
def rank_issues(space, order):
	"""Save the order the team chose for its open issues."""
	if not visibility.can_manage(space):
		frappe.throw(_("Only the facilitator, secretary or a space leader can rank issues."), frappe.PermissionError)
	for idx, name in enumerate(_loads(order), 1):
		doc = frappe.get_doc("Pulse Issue", name)
		if doc.space != space or doc.status != "Open":
			continue
		doc.check_permission("read")
		if cint(doc.rank) != idx:
			doc.rank = idx
			_system_save(doc)
	return {"ok": True}


@frappe.whitelist()
def update_issue_notes(issue, discussion):
	doc = frappe.get_doc("Pulse Issue", issue)
	doc.check_permission("read")
	if not (visibility.can_manage(doc.space) or frappe.session.user in (doc.issue_owner, doc.raised_by)):
		frappe.throw(_("You cannot edit this issue."), frappe.PermissionError)
	doc.discussion = discussion
	_system_save(doc)
	return {"ok": True}


@frappe.whitelist()
def close_issue(issue, outcome, resolution=None, meeting=None):
	"""Solved or Dropped, optionally recorded against the meeting."""
	if outcome not in ("Solved", "Dropped", "Open"):
		frappe.throw(_("Unknown outcome."))
	doc = frappe.get_doc("Pulse Issue", issue)
	doc.check_permission("write")
	doc.status = outcome
	if resolution is not None:
		doc.resolution = resolution
	doc.save()
	if meeting and outcome != "Open":
		m = _meeting(meeting)
		if m.space == doc.space:
			doc.solved_in = m.name
			_system_save(doc)
	return doc.as_dict()


@frappe.whitelist()
def escalate_issue(issue, target_space, note=None, meeting=None):
	"""Send an issue to another space, keeping its history and a link both ways."""
	doc = frappe.get_doc("Pulse Issue", issue)
	doc.check_permission("write")
	if doc.status != "Open":
		frappe.throw(_("Only an open issue can be escalated."))
	if target_space == doc.space or not visibility.can_list_space(target_space):
		frappe.throw(_("Choose another space to escalate to."))
	leaders = space_leaders(target_space)
	details = doc.details or ""
	if note:
		details = "<p>{0}</p>{1}".format(escape_html(note), details)
	new = frappe.get_doc(
		{
			"doctype": "Pulse Issue",
			"space": target_space,
			"title": doc.title,
			"details": details,
			"visibility": doc.visibility,
			"issue_owner": leaders[0] if leaders else None,
			"raised_by": doc.raised_by,
			"escalated_from": doc.name,
			"reference_doctype": doc.reference_doctype,
			"reference_name": doc.reference_name,
		}
	)
	new.flags.pulse_system = True
	new.insert(ignore_permissions=True)
	doc.status = "Escalated"
	doc.escalated_to = target_space
	doc.escalated_issue = new.name
	doc.closed_on = today()
	if meeting:
		m = _meeting(meeting)
		if m.space == doc.space:
			doc.solved_in = m.name
	_system_save(doc)
	_notify(
		leaders,
		_("Issue escalated to {0}: {1}").format(target_space, doc.title),
		"Pulse Issue",
		new.name,
	)
	return {"issue": doc.as_dict(), "escalated_issue": new.name}


@frappe.whitelist()
def add_decision(space, decision, meeting=None, issue=None, reason=None, review_date=None, publish=1,
	supersedes=None, reference_doctype=None, reference_name=None, priority=None):
	doc = frappe.get_doc(
		{
			"doctype": "Pulse Decision",
			"space": space,
			"decision": decision,
			"meeting": meeting,
			"issue": issue,
			"priority": priority,
			"reason": reason,
			"review_date": review_date,
			"publish": cint(publish),
			"supersedes": supersedes,
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
		}
	)
	doc.insert()
	return doc.as_dict()


# ---------------------------------------------------------------- headlines and messages


@frappe.whitelist()
def add_headline(space, headline, kind="General", meeting=None):
	doc = frappe.get_doc({"doctype": "Pulse Headline", "space": space, "headline": headline, "kind": kind, "meeting": meeting})
	doc.insert()
	return doc.as_dict()


@frappe.whitelist()
def add_message(from_space, message, targets, meeting=None, communicator=None):
	doc = frappe.get_doc(
		{
			"doctype": "Pulse Message",
			"from_space": from_space,
			"from_meeting": meeting,
			"message": message,
			"communicator": communicator,
			"targets": [{"space": s} for s in _loads(targets)],
		}
	)
	doc.insert()
	return doc.as_dict()


@frappe.whitelist()
def acknowledge_message(message, meeting):
	m = _meeting(meeting)
	_require_run(m)
	row = frappe.get_all(
		"Pulse Message Target",
		filters={"parent": message, "parenttype": "Pulse Message", "space": m.space},
		pluck="name",
	)
	if not row:
		frappe.throw(_("This message was not sent to {0}.").format(m.space))
	frappe.db.set_value("Pulse Message Target", row[0], "acknowledged_in", m.name, update_modified=False)
	return {"ok": True}


def _send_message(msg):
	"""Mark a message sent and create the follow-up action for its communicator."""
	msg.status = "Sent"
	msg.sent_at = now_datetime()
	_system_save(msg)
	if msg.communicator:
		action = frappe.get_doc(
			{
				"doctype": "Pulse Action",
				"space": msg.from_space,
				"title": _("Communicate: {0}").format(msg.message)[:140],
				"assigned_to": msg.communicator,
				"assigned_by": frappe.session.user,
				"due_date": default_due_date(),
				"message": msg.name,
				"source_meeting": msg.from_meeting,
			}
		)
		action.flags.pulse_system = True
		action.insert(ignore_permissions=True)


# ---------------------------------------------------------------- publishing


def _user_label(user):
	return frappe.db.get_value("User", user, "full_name") or user


def _distribution(doc):
	"""Who receives what when a concluded meeting is published."""
	attendees = [r.user for r in doc.attendees]
	full = enabled_users(attendees + active_members(doc.space))
	full_set = set(full)

	new_actions = frappe.get_all(
		"Pulse Action",
		filters={"source_meeting": doc.name, "status": ["!=", "Cancelled"], "message": ["is", "not set"]},
		fields=["name", "title", "assigned_to", "due_date", "visibility", "assigned_by"],
		order_by="creation asc",
	)
	action_only = {}
	for a in new_actions:
		if a.assigned_to not in full_set or a.visibility == "Restricted":
			action_only.setdefault(a.assigned_to, []).append(a)

	messages = []
	for m in frappe.get_all("Pulse Message", filters={"from_meeting": doc.name, "status": "Draft"}, fields=["name", "message", "communicator"]):
		targets = frappe.get_all("Pulse Message Target", filters={"parent": m.name, "parenttype": "Pulse Message"}, pluck="space")
		recipients = []
		for t in targets:
			recipients += active_members(t)
		messages.append({**m, "targets": targets, "recipients": enabled_users(recipients)})
	return full, action_only, new_actions, messages


@frappe.whitelist()
def publish_preview(meeting):
	doc = _meeting(meeting)
	_require_run(doc)
	_require_status(doc, "Concluded")
	full, action_only, new_actions, messages = _distribution(doc)
	return {
		"full": [{"user": u, "full_name": _user_label(u)} for u in full],
		"action_only": [
			{"user": u, "full_name": _user_label(u), "actions": [a.title for a in items]} for u, items in action_only.items()
		],
		"messages": [
			{"name": m["name"], "message": m["message"], "targets": m["targets"], "recipient_count": len(m["recipients"])}
			for m in messages
		],
		"summary_html": render_summary(doc),
	}


def render_summary(doc):
	"""The published summary. Draft notes and Restricted items are never included."""
	return frappe.render_template(
		"bizhub_pulse/templates/includes/meeting_summary.html", _summary_context(doc), is_path=True
	)


def _summary_context(doc):
	return {
		"meeting": doc,
		"present": [_user_label(r.user) for r in doc.attendees if r.attendance == "Present"],
		"absent": [_user_label(r.user) for r in doc.attendees if r.attendance != "Present"],
		"headlines": frappe.get_all(
			"Pulse Headline",
			filters={"space": doc.space},
			or_filters=[["meeting", "=", doc.name], ["creation", ">=", _since(doc)]],
			fields=["headline", "kind"],
			order_by="creation asc",
		),
		"decisions": frappe.get_all(
			"Pulse Decision",
			filters={"meeting": doc.name, "publish": 1, "status": "Active"},
			fields=["decision", "reason", "review_date"],
			order_by="creation asc",
		),
		"actions": [
			{**a, "owner_name": _user_label(a.assigned_to)}
			for a in frappe.get_all(
				"Pulse Action",
				filters={"source_meeting": doc.name, "visibility": "Team", "status": ["!=", "Cancelled"]},
				fields=["title", "assigned_to", "due_date"],
				order_by="due_date asc",
			)
		],
		"issues": frappe.get_all(
			"Pulse Issue",
			filters={"solved_in": doc.name, "visibility": "Team"},
			fields=["title", "status", "resolution", "escalated_to"],
		),
		"messages": frappe.get_all("Pulse Message", filters={"from_meeting": doc.name}, fields=["message"]),
		"priorities": [
			{**p, "owner_name": _user_label(p.priority_owner)}
			for p in frappe.get_all(
				"Pulse Priority",
				filters={"space": doc.space, "visibility": "Team", "status": ["in", ["On Track", "Off Track"]]},
				fields=["title", "priority_owner", "status", "due_date", "kind", "current_value", "target_value", "unit"],
				order_by="due_date asc",
			)
		],
		"url": frappe.utils.get_url_to_form("Pulse Meeting", doc.name),
		"minutes": [
			{"topic": r.topic, "html": sanitize_html(r.minutes or "")} for r in doc.minutes if (r.minutes or "").strip()
		],
	}


@frappe.whitelist()
def publish(meeting, exclude_users=None, exclude_messages=None, personal=1):
	doc = _meeting(meeting, lock=True)
	_require_run(doc)
	_require_status(doc, "Concluded")
	exclude_users = set(_loads(exclude_users))
	exclude_messages = set(_loads(exclude_messages))
	full, action_only, _new_actions, messages = _distribution(doc)
	now = now_datetime()

	# Messages go first: sending them is part of what the summary reports.
	for m in messages:
		if m["name"] in exclude_messages:
			continue
		msg = frappe.get_doc("Pulse Message", m["name"])
		_send_message(msg)
		recipients = [u for u in m["recipients"] if u not in exclude_users]
		_email(
			recipients,
			_("Message from {0}").format(doc.space),
			"bizhub_pulse/templates/emails/pulse_message.html",
			{"message": msg, "space": doc.space},
			"Pulse Message",
			msg.name,
		)
		for u in recipients:
			doc.append("publications", {"user": u, "scope": "Message", "reference": msg.name, "sent_at": now})

	summary = render_summary(doc)
	full = [u for u in full if u not in exclude_users]
	_email(
		full,
		_("Summary: {0}").format(doc.title),
		"bizhub_pulse/templates/emails/pulse_summary.html",
		{"summary": summary, "meeting": doc},
		"Pulse Meeting",
		doc.name,
	)
	for u in full:
		doc.append("publications", {"user": u, "scope": "Full Summary", "reference": doc.name, "sent_at": now})

	for user, items in action_only.items():
		if user in exclude_users:
			continue
		_email(
			[user],
			_("New action from {0}").format(doc.space),
			"bizhub_pulse/templates/emails/pulse_actions.html",
			{"actions": items, "meeting": doc},
			"Pulse Meeting",
			doc.name,
		)
		for a in items:
			doc.append("publications", {"user": user, "scope": "Action Only", "reference": a.name, "sent_at": now})

	if cint(personal):
		for user in enabled_users([u for u in dict.fromkeys(full + list(action_only)) if u not in exclude_users]):
			ctx = my_pulse_digest(user, doc.name)
			if not ctx["count"]:
				continue
			_email(
				[user],
				_("Your Pulse after {0}: {1} open, {2} overdue").format(doc.title, ctx["open_count"], len(ctx["overdue"])),
				"bizhub_pulse/templates/emails/pulse_my_pulse.html",
				ctx,
				"Pulse Meeting",
				doc.name,
			)

	for name in frappe.get_all("Pulse Decision", filters={"meeting": doc.name}, pluck="name"):
		decision = frappe.get_doc("Pulse Decision", name)
		decision.locked = 1
		_system_save(decision)

	doc.summary = summary
	doc.status = "Published"
	doc.published_at = now
	_system_save(doc)
	visibility.clear_cache()
	return {"status": doc.status, "sent": len(doc.publications)}


def my_pulse_digest(user, meeting=None):
	"""Everything one person owns across all their spaces, for their personal email.
	Only items the person owns or assigned, so nothing they could not already open."""
	day = getdate(today())
	actions = frappe.get_all(
		"Pulse Action",
		filters={"assigned_to": user, "status": "Open"},
		fields=["name", "title", "space", "due_date", "source_meeting", "carried_over"],
		order_by="due_date asc",
		limit_page_length=200,
	)
	for a in actions:
		a.new = bool(meeting and a.source_meeting == meeting)
		a.url = frappe.utils.get_url_to_form("Pulse Action", a.name)
	week_end = add_days(day, 7)
	readable = visibility.readable_spaces(user) if not visibility.is_admin(user) else None
	upcoming = frappe.db.sql(
		"""select distinct m.name, m.title, m.space, m.scheduled_start from `tabPulse Meeting` m
		join `tabPulse Meeting Attendee` a on a.parent = m.name and a.parenttype = 'Pulse Meeting'
		where a.user = %s and m.status = 'Scheduled' and m.scheduled_start >= %s and m.scheduled_start < %s
		order by m.scheduled_start asc limit 10""",
		(user, day, add_days(day, 14)),
		as_dict=True,
	)
	upcoming = [m for m in upcoming if readable is None or m.space in readable]
	for m in upcoming:
		m.url = frappe.utils.get_url(f"/app/pulse-room/{m.name}")
	ctx = {
		"user_name": frappe.utils.get_fullname(user),
		"new": [a for a in actions if a.new],
		"overdue": [a for a in actions if not a.new and getdate(a.due_date) < day],
		"this_week": [a for a in actions if not a.new and day <= getdate(a.due_date) <= week_end],
		"later": [a for a in actions if not a.new and getdate(a.due_date) > week_end],
		"issues": frappe.get_all(
			"Pulse Issue", filters={"issue_owner": user, "status": "Open"}, fields=["name", "title", "space"],
			order_by="space asc, `rank` asc", limit_page_length=50,
		),
		"priorities": frappe.get_all(
			"Pulse Priority", filters={"priority_owner": user, "status": ["in", ["On Track", "Off Track"]]},
			fields=["name", "title", "space", "status", "due_date"], order_by="due_date asc", limit_page_length=20,
		),
		"waiting_on": frappe.get_all(
			"Pulse Action", filters={"assigned_by": user, "assigned_to": ["!=", user], "status": "Open"},
			fields=["name", "title", "assigned_to", "due_date", "space"], order_by="due_date asc", limit_page_length=30,
		),
		"meetings": upcoming,
		"url": frappe.utils.get_url("/app/my-pulse"),
	}
	for a in ctx["waiting_on"]:
		a.owner_name = frappe.utils.get_fullname(a.assigned_to)
		a.overdue = getdate(a.due_date) < day
	ctx["open_count"] = len(actions)
	ctx["count"] = len(actions) + len(ctx["issues"]) + len(ctx["priorities"]) + len(ctx["waiting_on"])
	return ctx


def _email(recipients, subject, template, context, reference_doctype, reference_name):
	recipients = enabled_users(recipients)
	if not recipients:
		return
	frappe.sendmail(
		recipients=recipients,
		subject=subject,
		template=template.rsplit("/", 1)[-1].replace(".html", ""),
		args=context,
		reference_doctype=reference_doctype,
		reference_name=reference_name,
		delayed=True,
	)


def _notify(users, subject, doctype, name):
	for user in enabled_users(users):
		frappe.get_doc(
			{
				"doctype": "Notification Log",
				"for_user": user,
				"type": "Alert",
				"subject": escape_html(subject),
				"document_type": doctype,
				"document_name": name,
				"from_user": frappe.session.user,
			}
		).insert(ignore_permissions=True)


# ---------------------------------------------------------------- My Pulse and linked records


@frappe.whitelist()
def my_pulse():
	user = frappe.session.user
	day = getdate(today())
	actions = frappe.get_list(
		"Pulse Action",
		filters={"assigned_to": user, "status": ["in", ["Open", "Done"]]},
		fields=ACTION_FIELDS + ["space"],
		order_by="due_date asc",
		limit_page_length=200,
	)
	open_actions = [a for a in actions if a.status == "Open"]
	recent_done = [a for a in actions if a.status == "Done" and a.completed_on and getdate(a.completed_on) >= add_days(day, -7)]
	issues = frappe.get_list(
		"Pulse Issue",
		filters={"issue_owner": user, "status": "Open"},
		fields=["name", "title", "space", "rank"],
		order_by="space asc, `rank` asc",
		limit_page_length=200,
	)
	spaces = sorted(visibility.readable_spaces(user) if not visibility.is_admin(user) else frappe.get_all("Pulse Space", filters={"disabled": 0}, pluck="name"))
	meetings = frappe.get_list(
		"Pulse Meeting",
		filters={"status": ["in", ["Scheduled", "In Progress", "Concluded"]], "scheduled_start": [">=", add_days(day, -7)]},
		fields=["name", "title", "space", "scheduled_start", "status"],
		order_by="scheduled_start asc",
		limit_page_length=20,
	)
	return {
		"overdue": [a for a in open_actions if getdate(a.due_date) < day],
		"due": [a for a in open_actions if getdate(a.due_date) >= day],
		"done_recently": recent_done,
		"issues": issues,
		"spaces": spaces,
		"meetings": meetings,
		"priorities": frappe.get_list(
			"Pulse Priority",
			filters={"priority_owner": user, "status": ["in", ["On Track", "Off Track"]]},
			fields=["name", "title", "space", "status", "due_date"],
			order_by="due_date asc",
			limit_page_length=50,
		),
		"assigned_by_me_open": frappe.get_list(
			"Pulse Action",
			filters={"assigned_by": user, "assigned_to": ["!=", user], "status": "Open"},
			fields=["name", "title", "assigned_to", "due_date", "space"],
			order_by="due_date asc",
			limit_page_length=50,
		),
	}


@frappe.whitelist()
def linked_items(doctype, name):
	"""Open Pulse issues and actions linked to an ERPNext record, for its form sidebar."""
	if not frappe.has_permission(doctype, "read", name):
		return {"issues": [], "actions": []}
	filters = {"reference_doctype": doctype, "reference_name": name}
	return {
		"issues": frappe.get_list(
			"Pulse Issue", filters={**filters, "status": "Open"}, fields=["name", "title", "space"], limit_page_length=20
		),
		"actions": frappe.get_list(
			"Pulse Action",
			filters={**filters, "status": "Open"},
			fields=["name", "title", "assigned_to", "due_date", "space"],
			limit_page_length=20,
		),
	}


@frappe.whitelist()
def contribute_spaces():
	"""Spaces the caller can add issues and actions to (for pickers)."""
	user = frappe.session.user
	if visibility.is_admin(user):
		return frappe.get_all("Pulse Space", filters={"disabled": 0}, pluck="name", order_by="space_name asc")
	return sorted(visibility.contribute_spaces(user))
