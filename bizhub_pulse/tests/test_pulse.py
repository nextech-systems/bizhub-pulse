# Copyright (c) 2026, NextTech BizHub and contributors
# License: MIT. See LICENSE
"""BizHub Pulse: permissions and the weekly cycle.

Synthetic users and spaces only. Run with:
    bench --site STAGING run-tests --app bizhub_pulse
"""

import frappe
from frappe.utils import add_days, add_to_date, getdate, now_datetime, today

from bizhub_pulse import api, scheduler, visibility

try:
	from frappe.tests.utils import FrappeTestCase
except ImportError:  # pragma: no cover
	from frappe.tests import IntegrationTestCase as FrappeTestCase

DOM = "pulse-test.invalid"
U = {k: f"{k}@{DOM}" for k in ("padmin", "lead", "mem", "mem2", "obs", "out", "boss", "blead", "secret", "sysman")}
SP = {"A": "PT Team A", "B": "PT Team B", "S": "PT Secret", "C": "PT Company", "P": "PT Person Mem"}
CONTENT = ("Pulse Space", "Pulse Meeting", "Pulse Issue", "Pulse Decision", "Pulse Action", "Pulse Headline", "Pulse Message", "Pulse Meeting Notes", "Pulse Priority")


def as_user(user):
	frappe.set_user(user)
	visibility.clear_cache()


def make_user(email, roles):
	if not frappe.db.exists("User", email):
		u = frappe.get_doc({"doctype": "User", "email": email, "first_name": email.split("@")[0], "send_welcome_email": 0})
		u.insert(ignore_permissions=True)
		u.add_roles(*roles)


def employee(user, reports_to=None):
	name = "PT-EMP-" + user.split("@")[0]
	if not frappe.db.exists("Employee", name):
		frappe.get_doc(
			{"doctype": "Employee", "name": name, "first_name": user.split("@")[0], "employee_name": user.split("@")[0],
			 "user_id": user, "reports_to": reports_to, "status": "Active"}
		).db_insert()
	return name


def space(name, space_type="Team", vis="Private", members=(), person=None, **kw):
	if frappe.db.exists("Pulse Space", name):
		return frappe.get_doc("Pulse Space", name)
	doc = frappe.get_doc(
		{"doctype": "Pulse Space", "space_name": name, "space_type": space_type, "visibility": vis, "person_user": person,
		 "default_template": "Weekly Team Meeting", "members": [{"user": u, "member_role": r} for u, r in members], **kw}
	)
	doc.insert(ignore_permissions=True)
	return doc


class TestPulse(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		frappe.flags.mute_emails = True
		for k, email in U.items():
			make_user(email, {"padmin": ["Pulse Admin"], "sysman": ["System Manager"], "secret": ["Pulse User", "System Manager"]}.get(k, ["Pulse User"]))
		if not frappe.db.exists("Email Account", {"default_outgoing": 1, "enable_outgoing": 1}):
			frappe.get_doc(
				{"doctype": "Email Account", "email_account_name": "PT Outgoing", "email_id": f"noreply@{DOM}",
				 "enable_outgoing": 1, "default_outgoing": 1, "smtp_server": "127.0.0.1", "smtp_port": 25,
				 "no_smtp_authentication": 1}
			).db_insert()
		boss = employee(U["boss"])
		employee(U["mem"], reports_to=boss)
		space(SP["A"], members=[(U["lead"], "Leader"), (U["mem"], "Member"), (U["mem2"], "Member"), (U["obs"], "Observer")])
		space(SP["B"], members=[(U["blead"], "Leader")])
		space(SP["S"], vis="Secret", members=[(U["secret"], "Leader")])
		space(SP["C"], space_type="Company", members=[(U["lead"], "Leader")])
		space(SP["P"], space_type="Person", person=U["mem"])
		frappe.db.commit()

	def setUp(self):
		as_user("Administrator")

	def tearDown(self):
		as_user("Administrator")

	# ------------------------------------------------------------ helpers

	def issue(self, user, space_name, title="pt issue", **kw):
		as_user(user)
		doc = frappe.get_doc({"doctype": "Pulse Issue", "space": space_name, "title": title, **kw}).insert()
		as_user("Administrator")
		return doc

	def action(self, user, space_name, owner, title="pt action", **kw):
		as_user(user)
		doc = frappe.get_doc({"doctype": "Pulse Action", "space": space_name, "title": title, "assigned_to": owner, **kw}).insert()
		as_user("Administrator")
		return doc

	def sees(self, user, doc):
		"""Read access by document check AND list, which must agree."""
		as_user(user)
		by_doc = frappe.has_permission(doc.doctype, "read", doc=frappe.get_doc(doc.doctype, doc.name), user=user)
		try:
			by_list = doc.name in frappe.get_list(doc.doctype, filters={"name": doc.name}, pluck="name")
		except frappe.PermissionError:
			by_list = False  # no role on the DocType at all
		as_user("Administrator")
		self.assertEqual(bool(by_doc), by_list, f"{doc.doctype} {doc.name}: document check and list disagree for {user}")
		return by_list

	# ------------------------------------------------------------ spaces

	def test_01_space_listing(self):
		as_user(U["out"])
		names = set(frappe.get_list("Pulse Space", pluck="name"))
		self.assertIn(SP["A"], names, "a Private team space is listable")
		self.assertIn(SP["C"], names, "the company space is visible to all")
		self.assertNotIn(SP["S"], names, "a Secret space is hidden")
		self.assertNotIn(SP["P"], names, "someone else's Person space is hidden")
		as_user(U["padmin"])
		self.assertIn(SP["S"], frappe.get_list("Pulse Space", pluck="name"), "Pulse Admins can read Secret spaces")

	def test_01b_install_defaults(self):
		self.assertEqual(len(frappe.get_all("Pulse Meeting Template", filters={"name": ["in", ["Weekly Team Meeting", "Weekly Leadership Meeting", "Daily Huddle"]]})), 3)
		self.assertTrue(frappe.get_all("Pulse Linkable DocType", filters={"parent": "Pulse Settings"}), "first install fills the linkable forms")
		self.assertEqual(frappe.db.get_single_value("Pulse Settings", "default_due_days"), 7)

	def test_01c_other_guards_run_first(self):
		"""Another app's Version/Comment hook keeps its place ahead of Pulse's."""
		hooks = frappe.get_hooks("has_permission", {}) or {}
		for dt in ("Version", "Comment"):
			order = list(reversed(list(hooks.get(dt, [])) + list(hooks.get("*", []))))
			ours = "bizhub_pulse.visibility." + ("version" if dt == "Version" else "comment") + "_has_permission"
			self.assertIn(ours, order)
			others = [h for h in order if not h.startswith("bizhub_pulse.")]
			if others:
				self.assertLess(order.index(others[0]), order.index(ours), f"{dt}: {others[0]} is asked before Pulse")

	def test_02_only_admin_creates_spaces(self):
		as_user(U["lead"])
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc({"doctype": "Pulse Space", "space_name": "PT Rogue", "space_type": "Team"}).insert()

	def test_03_leader_cannot_change_visibility(self):
		as_user(U["lead"])
		doc = frappe.get_doc("Pulse Space", SP["A"])
		doc.visibility = "Secret"
		with self.assertRaises(frappe.PermissionError):
			doc.save()

	# ------------------------------------------------------------ issues and actions

	def test_10_team_issue_visibility(self):
		doc = self.issue(U["mem"], SP["A"], "pt team issue")
		for user in ("lead", "mem", "mem2", "obs", "padmin"):
			self.assertTrue(self.sees(U[user], doc), user)
		for user in ("out", "blead", "secret", "boss"):
			self.assertFalse(self.sees(U[user], doc), user)

	def test_11_observer_cannot_contribute(self):
		as_user(U["obs"])
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc({"doctype": "Pulse Issue", "space": SP["A"], "title": "x"}).insert()

	def test_12_outsider_cannot_create_in_space(self):
		as_user(U["out"])
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc({"doctype": "Pulse Action", "space": SP["A"], "title": "x", "assigned_to": U["out"]}).insert()

	def test_13_restricted_action(self):
		doc = self.action(U["lead"], SP["A"], U["mem"], "pt restricted", visibility="Restricted")
		for user in ("lead", "mem", "boss", "padmin"):
			self.assertTrue(self.sees(U[user], doc), user)
		for user in ("mem2", "obs", "out", "blead"):
			self.assertFalse(self.sees(U[user], doc), user)

	def test_14_team_action_outside_owner(self):
		doc = self.action(U["lead"], SP["A"], U["out"], "pt for outsider")
		self.assertTrue(self.sees(U["out"], doc), "the owner sees their action even outside the space")
		self.assertTrue(self.sees(U["mem2"], doc))
		self.assertFalse(self.sees(U["blead"], doc))
		self.assertFalse(self.sees(U["boss"], doc), "managers see only Restricted items of their reports outside the space")

	def test_15_forged_assigner_ignored(self):
		as_user(U["mem"])
		doc = frappe.get_doc({"doctype": "Pulse Action", "space": SP["A"], "title": "pt forged", "assigned_to": U["mem2"], "assigned_by": U["lead"]})
		doc.insert()
		self.assertEqual(doc.assigned_by, U["mem"])

	def test_16_owner_limited_to_status(self):
		doc = self.action(U["lead"], SP["A"], U["mem"], "pt limited", evidence_required=1)
		as_user(U["mem"])
		d = frappe.get_doc("Pulse Action", doc.name)
		d.title = "renamed"
		with self.assertRaises(frappe.PermissionError):
			d.save()
		d = frappe.get_doc("Pulse Action", doc.name)
		d.status = "Done"
		with self.assertRaises(frappe.ValidationError):
			d.save()  # evidence required
		d = frappe.get_doc("Pulse Action", doc.name)
		d.status = "Done"
		d.completion_note = "delivered"
		d.save()
		self.assertEqual(str(d.completed_on), today())
		d = frappe.get_doc("Pulse Action", doc.name)
		d.status = "Cancelled"
		with self.assertRaises(frappe.PermissionError):
			d.save()

	def test_17_move_into_space_not_allowed(self):
		doc = self.issue(U["mem"], SP["A"], "pt mover")
		as_user(U["mem"])
		d = frappe.get_doc("Pulse Issue", doc.name)
		d.space = SP["S"]
		with self.assertRaises(frappe.PermissionError):
			d.save()

	def test_18_protected_fields(self):
		doc = self.issue(U["mem"], SP["A"], "pt protected")
		self.assertEqual(doc.raised_by, U["mem"])
		as_user(U["lead"])
		d = frappe.get_doc("Pulse Issue", doc.name)
		d.raised_by = U["lead"]
		with self.assertRaises(frappe.PermissionError):
			d.save()
		as_user(U["lead"])
		m = frappe.get_doc({"doctype": "Pulse Meeting", "space": SP["A"], "scheduled_start": add_to_date(now_datetime(), days=30)}).insert()
		m.status = "Published"
		with self.assertRaises(frappe.PermissionError):
			m.save()

	def test_19_sharing_refused(self):
		doc = self.issue(U["mem"], SP["A"], "pt share")
		for user in ("Administrator", U["lead"]):
			as_user(user)
			with self.assertRaises(frappe.PermissionError):
				frappe.share.add("Pulse Issue", doc.name, U["out"], read=1)

	def test_20_person_space(self):
		doc = self.issue("Administrator", SP["P"], "pt personal")
		self.assertTrue(self.sees(U["mem"], doc))
		self.assertTrue(self.sees(U["boss"], doc))
		self.assertFalse(self.sees(U["lead"], doc))

	def test_21_secret_space_content(self):
		doc = self.issue(U["secret"], SP["S"], "pt secret")
		self.assertTrue(self.sees(U["padmin"], doc))
		self.assertFalse(self.sees(U["lead"], doc))
		self.assertFalse(self.sees(U["out"], doc))

	def test_22_reference_needs_read(self):
		note = frappe.get_doc({"doctype": "Note", "title": "pt private note " + frappe.generate_hash(length=6), "public": 0}).insert()
		as_user(U["mem"])
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc({"doctype": "Pulse Issue", "space": SP["A"], "title": "x", "reference_doctype": "Note", "reference_name": note.name}).insert()

	def test_23_linked_record_sidebar(self):
		note = frappe.get_doc({"doctype": "Note", "title": "pt public note " + frappe.generate_hash(length=6), "public": 1}).insert()
		as_user(U["mem"])
		issue = api.add_issue(SP["A"], "pt about the note", reference_doctype="Note", reference_name=note.name)
		as_user(U["lead"])
		api.add_action(SP["A"], "pt restricted about the note", U["mem2"], visibility="Restricted", reference_doctype="Note", reference_name=note.name)
		as_user(U["mem"])
		seen = api.linked_items("Note", note.name)
		self.assertIn(issue["name"], [i.name for i in seen["issues"]])
		self.assertEqual(seen["actions"], [], "a member does not see another's Restricted action in the sidebar")
		as_user(U["out"])
		self.assertEqual(api.linked_items("Note", note.name), {"issues": [], "actions": []})

	def test_24_history_and_comments_follow_the_record(self):
		doc = self.issue(U["secret"], SP["S"], "pt secret history", visibility="Restricted")
		as_user(U["secret"])
		d = frappe.get_doc("Pulse Issue", doc.name)
		d.details = "<p>changed secretly</p>"
		d.save()
		# Frappe skips Version records in test mode, so write one the way a real save would.
		frappe.get_doc({"doctype": "Version", "ref_doctype": "Pulse Issue", "docname": doc.name,
			"data": frappe.as_json({"changed": [["details", "", "<p>changed secretly</p>"]]})}).insert(ignore_permissions=True)
		frappe.get_doc({"doctype": "Comment", "comment_type": "Comment", "reference_doctype": "Pulse Issue",
			"reference_name": doc.name, "content": "secret comment"}).insert(ignore_permissions=True)
		as_user("Administrator")
		version = frappe.get_all("Version", filters={"ref_doctype": "Pulse Issue", "docname": doc.name}, pluck="name")
		comment = frappe.get_all("Comment", filters={"reference_doctype": "Pulse Issue", "reference_name": doc.name, "comment_type": "Comment"}, pluck="name")
		self.assertTrue(version and comment)
		# Both are System Managers (who can list Version and Comment); only one is in the Secret space.
		for user, expected in (("sysman", False), ("secret", True)):
			as_user(U[user])
			self.assertEqual(bool(frappe.get_list("Version", filters={"name": version[0]}, pluck="name")), expected, f"Version list, {user}")
			self.assertEqual(bool(frappe.get_list("Comment", filters={"name": comment[0]}, pluck="name")), expected, f"Comment list, {user}")
			self.assertEqual(bool(frappe.has_permission("Version", "read", doc=frappe.get_doc("Version", version[0]), user=U[user])), expected)
			self.assertEqual(bool(frappe.has_permission("Comment", "read", doc=frappe.get_doc("Comment", comment[0]), user=U[user])), expected)
		as_user(U["sysman"])
		as_user("Administrator")
		note = frappe.get_doc({"doctype": "Note", "title": "pt plain note " + frappe.generate_hash(length=6), "public": 1}).insert()
		plain = frappe.get_doc({"doctype": "Version", "ref_doctype": "Note", "docname": note.name, "data": "{}"}).insert(ignore_permissions=True)
		as_user(U["sysman"])
		self.assertIn(plain.name, frappe.get_list("Version", filters={"name": plain.name}, pluck="name"), "history of non-Pulse records is unaffected")

	# ------------------------------------------------------------ priorities

	def priority(self, user, space_name, title="pt priority", **kw):
		as_user(user)
		values = {"doctype": "Pulse Priority", "space": space_name, "title": title, "priority_owner": U["mem"],
			"due_date": add_days(today(), 60), "success_criteria": "it is done", "kind": "Milestones",
			"milestones": [{"milestone": "step one", "due_date": add_days(today(), 10), "milestone_owner": U["mem2"]}]}
		values.update(kw)
		doc = frappe.get_doc(values).insert()
		as_user("Administrator")
		return doc

	def test_60_priority_visibility_and_creation(self):
		as_user(U["mem"])
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc({"doctype": "Pulse Priority", "space": SP["A"], "title": "x", "priority_owner": U["mem"],
				"due_date": add_days(today(), 30), "success_criteria": "x"}).insert()
		team = self.priority(U["lead"], SP["A"], "pt team priority", contributors=[{"user": U["blead"]}])
		for user in ("lead", "mem", "mem2", "obs", "padmin", "blead"):
			self.assertTrue(self.sees(U[user], team), user)
		for user in ("out", "boss", "secret"):
			self.assertFalse(self.sees(U[user], team), user)
		restricted = self.priority(U["lead"], SP["A"], "pt restricted priority", visibility="Restricted")
		for user in ("lead", "mem", "boss", "padmin"):
			self.assertTrue(self.sees(U[user], restricted), user)
		for user in ("mem2", "obs", "out"):
			self.assertFalse(self.sees(U[user], restricted), user)

	def test_61_owner_updates_progress_not_the_commitment(self):
		doc = self.priority(U["lead"], SP["A"], "pt measured", kind="Measured", milestones=[],
			measure_name="On-time dispatch", unit="%", start_value=72, target_value=90)
		as_user(U["mem"])
		api.update_priority(doc.name, current_value=78, support_needed="a second driver on Fridays")
		d = frappe.get_doc("Pulse Priority", doc.name)
		self.assertEqual(d.current_value, 78)
		self.assertEqual(str(d.current_as_of), today())
		d.target_value = 80
		with self.assertRaises(frappe.PermissionError):
			d.save()
		with self.assertRaises(frappe.PermissionError):
			api.update_priority(doc.name, status="Dropped")
		as_user(U["mem2"])
		with self.assertRaises(frappe.PermissionError):
			api.update_priority(doc.name, current_value=99)

	def test_62_milestones_set_on_and_off_track(self):
		doc = self.priority(U["lead"], SP["A"], "pt yard", milestones=[
			{"milestone": "quotes", "due_date": add_days(today(), -1), "milestone_owner": U["mem2"]},
			{"milestone": "works", "due_date": add_days(today(), 20)}])
		self.assertEqual(doc.status, "Off Track", "an overdue milestone puts it off track")
		as_user(U["mem2"])
		api.set_milestone(doc.name, 1, 1)
		d = frappe.get_doc("Pulse Priority", doc.name)
		self.assertEqual(d.status, "On Track")
		self.assertEqual(str(d.milestones[0].done_on), today())
		as_user(U["obs"])
		with self.assertRaises(frappe.PermissionError):
			api.set_milestone(doc.name, 2, 1)
		as_user(U["mem"])
		d = frappe.get_doc("Pulse Priority", doc.name)
		d.append("milestones", {"milestone": "sneaky", "due_date": add_days(today(), 5)})
		with self.assertRaises(frappe.PermissionError):
			d.save()

	def test_63_links_stay_in_their_space(self):
		doc = self.priority(U["lead"], SP["A"], "pt linked")
		as_user(U["lead"])
		issue = api.add_issue(SP["A"], "pt blocking the priority", priority=doc.name)
		action = api.add_action(SP["A"], "pt step for the priority", U["mem"], priority=doc.name)
		self.assertEqual(issue["priority"], doc.name)
		as_user(U["blead"])
		with self.assertRaises(frappe.ValidationError):
			api.add_issue(SP["B"], "pt wrong space", priority=doc.name)
		as_user(U["lead"])
		m = frappe.get_doc({"doctype": "Pulse Meeting", "space": SP["A"], "scheduled_start": add_to_date(now_datetime(), days=50)}).insert()
		state = api.get_meeting(m.name)
		row = next(p for p in state["priorities"] if p.name == doc.name)
		self.assertIn(action["name"], [a.name for a in row.open_actions])
		self.assertEqual(row.milestones_done, 0)
		as_user(U["mem2"])
		self.assertNotIn("pt restricted priority", [p.title for p in api.get_meeting(m.name)["priorities"]])

	def test_64_summary_lists_team_priorities_only(self):
		self.priority(U["lead"], SP["A"], "pt summary team")
		self.priority(U["lead"], SP["A"], "pt summary hidden", visibility="Restricted")
		as_user(U["lead"])
		m = frappe.get_doc({"doctype": "Pulse Meeting", "space": SP["A"], "scheduled_start": add_to_date(now_datetime(), days=51)}).insert()
		html = api.render_summary(m)
		self.assertIn("pt summary team", html)
		self.assertNotIn("pt summary hidden", html)

	# ------------------------------------------------------------ minutes and follow-up

	def test_70_minutes_by_topic(self):
		as_user(U["lead"])
		m = frappe.get_doc({"doctype": "Pulse Meeting", "space": SP["A"], "scheduled_start": add_to_date(now_datetime(), days=60)}).insert()
		api.save_minute(m.name, "Health and safety", "<p>One AIR form; report within 24 hours.</p>")
		api.save_minute(m.name, "Health and safety", "<p>One AIR form; report within 24 hours. PPE to be enforced.</p>")
		rows = api.save_minute(m.name, "Inventory", "<p>Minimums to be agreed.</p><script>alert(1)</script>")
		self.assertEqual([r["topic"] for r in rows], ["Health and safety", "Inventory"], "one row per topic, updated in place")
		as_user(U["mem"])
		with self.assertRaises(frappe.PermissionError):
			api.save_minute(m.name, "Sneaky", "x")
		self.assertTrue(self.sees(U["mem"], m), "members read the minutes with the meeting")
		self.assertFalse(self.sees(U["out"], m))
		as_user(U["lead"])
		html = api.render_summary(frappe.get_doc("Pulse Meeting", m.name))
		self.assertIn("PPE to be enforced", html)
		self.assertNotIn("<script>", html)
		api.start_meeting(m.name)
		api.conclude_meeting(m.name)
		api.publish(m.name)
		with self.assertRaises(frappe.ValidationError):
			api.save_minute(m.name, "Late", "x")

	def test_71_followup_is_live_and_filtered(self):
		as_user(U["lead"])
		m = frappe.get_doc({"doctype": "Pulse Meeting", "space": SP["A"], "scheduled_start": add_to_date(now_datetime(), days=61)}).insert()
		team = api.add_action(SP["A"], "pt follow team", U["mem"], meeting=m.name, due_date=add_days(today(), -2))
		api.add_action(SP["A"], "pt follow private", U["mem2"], meeting=m.name, visibility="Restricted")
		done = api.add_action(SP["A"], "pt follow done", U["mem"], meeting=m.name)
		api.add_issue(SP["A"], "pt follow issue", meeting=m.name)
		api.add_decision(SP["A"], "pt follow decision", meeting=m.name)
		as_user(U["mem"])
		api.complete_action(done["name"], "finished")
		lead_view = None
		as_user(U["lead"])
		lead_view = api.meeting_followup(m.name)
		self.assertEqual(lead_view["stats"]["actions"], 3)
		self.assertEqual(lead_view["stats"]["done"], 1)
		self.assertEqual(lead_view["stats"]["overdue"], 1)
		self.assertTrue(next(a for a in lead_view["actions"] if a.name == team["name"]).overdue)
		self.assertEqual(lead_view["stats"]["issues"], 1)
		self.assertEqual(len(lead_view["decisions"]), 1)
		as_user(U["obs"])
		obs_view = api.meeting_followup(m.name)
		self.assertEqual(obs_view["stats"]["actions"], 2, "Restricted actions are not counted for people who cannot see them")
		as_user(U["out"])
		with self.assertRaises(frappe.PermissionError):
			api.meeting_followup(m.name)

	def test_72_tangent(self):
		as_user(U["lead"])
		m = frappe.get_doc({"doctype": "Pulse Meeting", "space": SP["A"], "scheduled_start": add_to_date(now_datetime(), days=62)}).insert()
		as_user(U["mem"])
		with self.assertRaises(frappe.ValidationError):
			api.call_tangent(m.name)  # only while the meeting runs
		as_user(U["lead"])
		api.start_meeting(m.name)
		for u in (U["mem"], U["obs"], U["lead"]):
			frappe.cache().delete_value(f"pulse_tangent|{m.name}|{u}")
		frappe.cache().delete_value(f"pulse_tangent|{m.name}")
		as_user(U["mem"])
		r = api.call_tangent(m.name)
		self.assertTrue(r["sent"])
		self.assertEqual(r["tangent_count"], 1)
		self.assertEqual(api.call_tangent(m.name)["reason"], "wait", "the same person cannot repeat at once")
		as_user(U["obs"])
		self.assertEqual(api.call_tangent(m.name)["reason"], "already", "a second call within seconds is folded in")
		frappe.cache().delete_value(f"pulse_tangent|{m.name}")
		as_user(U["lead"])
		self.assertEqual(api.call_tangent(m.name)["tangent_count"], 2, "observers and leaders can call it too")
		as_user(U["out"])
		with self.assertRaises(frappe.PermissionError):
			api.call_tangent(m.name)
		as_user(U["lead"])
		api.conclude_meeting(m.name)
		self.assertIn("Tangents called", api.render_summary(frappe.get_doc("Pulse Meeting", m.name)))

	def test_74_dictation_flag(self):
		as_user(U["lead"])
		m = frappe.get_doc({"doctype": "Pulse Meeting", "space": SP["A"], "scheduled_start": add_to_date(now_datetime(), days=64)}).insert()
		frappe.cache().delete_value(f"pulse_dictation|{m.name}")
		as_user(U["mem"])
		with self.assertRaises(frappe.PermissionError):
			api.set_dictation(m.name, 1)  # only those running the meeting
		as_user(U["lead"])
		state = api.set_dictation(m.name, 1)
		self.assertEqual(state["by"], U["lead"])
		as_user(U["mem"])
		self.assertEqual(api.get_meeting(m.name)["dictation"]["by"], U["lead"], "everyone in the meeting is told")
		as_user(U["lead"])
		api.set_dictation(m.name, 0)
		self.assertFalse(api.get_meeting(m.name)["dictation"])

	def test_73_personal_pulse_email(self):
		as_user(U["lead"])
		m = frappe.get_doc({"doctype": "Pulse Meeting", "space": SP["A"], "scheduled_start": add_to_date(now_datetime(), days=63)}).insert()
		new = api.add_action(SP["A"], "pt mine new", U["mem"], meeting=m.name, due_date=add_days(today(), 5))
		old = api.add_action(SP["A"], "pt mine late", U["mem"], due_date=add_days(today(), -3))
		api.add_action(SP["A"], "pt someone else", U["mem2"], due_date=add_days(today(), 2))
		api.add_issue(SP["A"], "pt mine issue", issue_owner=U["mem"])
		ctx = api.my_pulse_digest(U["mem"], m.name)
		self.assertEqual([a.name for a in ctx["new"]], [new["name"]], "actions from this meeting are marked new")
		self.assertIn(old["name"], [a.name for a in ctx["overdue"]])
		titles = [a.title for k in ("new", "overdue", "this_week", "later") for a in ctx[k]]
		self.assertNotIn("pt someone else", titles, "only the person's own actions")
		self.assertTrue(ctx["issues"], "issues the person owns are listed")
		self.assertTrue(all(frappe.db.get_value("Pulse Issue", i.name, "issue_owner") == U["mem"] for i in ctx["issues"]))
		waiting = api.my_pulse_digest(U["lead"])["waiting_on"]
		self.assertTrue(waiting and all(frappe.db.get_value("Pulse Action", a.name, "assigned_by") == U["lead"] for a in waiting),
			"the assigner sees what they wait on, and only that")
		html = frappe.render_template("bizhub_pulse/templates/emails/pulse_my_pulse.html", ctx, is_path=True)
		self.assertIn("pt mine late", html)
		self.assertNotIn("pt someone else", html)
		api.start_meeting(m.name)
		api.conclude_meeting(m.name)
		frappe.db.set_value("Pulse Meeting", m.name, "concluded_at", add_days(now_datetime(), -1))
		from bizhub_pulse import scheduler
		q = lambda: frappe.db.count("Email Queue", {"reference_doctype": "Pulse Meeting", "reference_name": m.name})
		before = q()
		scheduler.unpublished_reminders()
		self.assertGreater(q(), before, "an unpublished meeting is chased")
		before = q()
		api.publish(m.name, personal=1)
		self.assertGreaterEqual(q() - before, 2, "the summary plus at least one personal Pulse email")
		before = q()
		scheduler.unpublished_reminders()
		self.assertEqual(q(), before, "no chasing once published")

	# ------------------------------------------------------------ the weekly cycle

	def test_30_full_cycle(self):
		start = add_to_date(now_datetime(), hours=1)
		old = self.action(U["lead"], SP["A"], U["mem"], "pt last week", due_date=add_days(today(), -1))
		carry = self.action(U["lead"], SP["A"], U["mem2"], "pt carry me", due_date=add_days(today(), -1))
		open_issue = self.issue(U["mem"], SP["A"], "pt late deliveries")

		as_user(U["lead"])
		m = frappe.get_doc({"doctype": "Pulse Meeting", "space": SP["A"], "scheduled_start": start, "facilitator": U["lead"]}).insert()
		self.assertEqual(len(m.sections), 7)
		self.assertEqual({a.user for a in m.attendees}, {U["lead"], U["mem"], U["mem2"], U["obs"]})
		as_user(U["mem"])
		with self.assertRaises(frappe.PermissionError):
			api.start_meeting(m.name)
		as_user(U["lead"])
		state = api.start_meeting(m.name)
		self.assertEqual(state["meeting"]["status"], "In Progress")
		names = [a.name for a in state["to_review"]]
		self.assertIn(old.name, names)
		self.assertIn(carry.name, names)
		api.goto_section(m.name, 5)
		api.review_action(old.name, m.name, "Done")
		api.review_action(carry.name, m.name, "Carry")
		self.assertEqual(frappe.db.get_value("Pulse Action", carry.name, "carried_over"), 1)
		api.goto_section(m.name, 6)
		decision = api.add_decision(SP["A"], "Check stock before promising dates", meeting=m.name, issue=open_issue.name)
		team_action = api.add_action(SP["A"], "pt rewrite promise rule", U["mem"], meeting=m.name, issue=open_issue.name)
		private_action = api.add_action(SP["A"], "pt private follow-up", U["mem2"], meeting=m.name, visibility="Restricted")
		outside_action = api.add_action(SP["A"], "pt tell the outsider", U["out"], meeting=m.name)
		api.close_issue(open_issue.name, "Solved", "rule changed", meeting=m.name)
		api.add_message(SP["A"], "Dispatch: confirm stock before dates", [SP["B"]], meeting=m.name, communicator=U["lead"])
		as_user(U["mem"])
		api.set_rating(m.name, 8)
		as_user(U["lead"])
		api.conclude_meeting(m.name)

		preview = api.publish_preview(m.name)
		full = {r["user"] for r in preview["full"]}
		self.assertIn(U["obs"], full)
		self.assertNotIn(U["out"], full)
		action_only = {r["user"]: r["actions"] for r in preview["action_only"]}
		self.assertEqual(set(action_only), {U["out"], U["mem2"]}, "outside owners and Restricted owners get only their action")
		self.assertNotIn("pt private follow-up", preview["summary_html"])
		self.assertIn("mem", preview["summary_html"].split("Absent")[0], "attendees started as Present appear as present")
		self.assertIn("pt rewrite promise rule", preview["summary_html"])
		self.assertEqual(preview["messages"][0]["recipient_count"], 1)

		api.publish(m.name, exclude_users=[U["obs"]])
		m.reload()
		self.assertEqual(m.status, "Published")
		scopes = {(p.user, p.scope) for p in m.publications}
		self.assertIn((U["out"], "Action Only"), scopes)
		self.assertNotIn((U["obs"], "Full Summary"), scopes)
		self.assertIn((U["blead"], "Message"), scopes)
		self.assertEqual(m.average_rating, 8)
		self.assertTrue(frappe.db.get_value("Pulse Decision", decision["name"], "locked"))
		msg = frappe.get_all("Pulse Message", filters={"from_meeting": m.name}, fields=["name", "status"])[0]
		self.assertEqual(msg.status, "Sent")
		self.assertTrue(frappe.db.exists("Pulse Action", {"message": msg.name, "assigned_to": U["lead"]}))

		# After publishing: the outsider has their action, not the meeting.
		self.assertTrue(self.sees(U["out"], frappe.get_doc("Pulse Action", outside_action["name"])))
		self.assertFalse(self.sees(U["out"], m))
		self.assertTrue(self.sees(U["mem"], m))

		# The receiving space sees the message in its next meeting.
		as_user(U["blead"])
		mb = frappe.get_doc({"doctype": "Pulse Meeting", "space": SP["B"], "scheduled_start": add_to_date(start, days=1)}).insert()
		state = api.get_meeting(mb.name)
		self.assertIn(msg.name, [x.name for x in state["incoming_messages"]])
		self.assertFalse(self.sees(U["blead"], m), "the receiving team sees the message, not the sender's meeting")

		# Published records are fixed.
		as_user(U["lead"])
		d = frappe.get_doc("Pulse Decision", decision["name"])
		d.decision = "changed"
		with self.assertRaises(frappe.PermissionError):
			d.save()
		new = api.add_decision(SP["A"], "Check stock and transport", supersedes=decision["name"])
		self.assertEqual(frappe.db.get_value("Pulse Decision", decision["name"], "status"), "Superseded")
		self.assertEqual(frappe.db.get_value("Pulse Decision", decision["name"], "superseded_by"), new["name"])
		m.reload()
		m.location = "elsewhere"
		with self.assertRaises(frappe.PermissionError):
			m.save()

	def test_31_escalation(self):
		doc = self.issue(U["mem"], SP["A"], "pt escalate me")
		as_user(U["lead"])
		out = api.escalate_issue(doc.name, SP["B"], note="<b>needs dispatch</b>")
		new = frappe.get_doc("Pulse Issue", out["escalated_issue"])
		self.assertEqual(new.space, SP["B"])
		self.assertEqual(new.issue_owner, U["blead"])
		self.assertEqual(new.raised_by, U["mem"])
		self.assertIn("&lt;b&gt;", new.details)
		self.assertTrue(self.sees(U["blead"], new))
		self.assertTrue(self.sees(U["mem"], new), "the original raiser can follow it")
		self.assertFalse(self.sees(U["mem2"], new))
		self.assertEqual(frappe.db.get_value("Pulse Issue", doc.name, "status"), "Escalated")
		as_user(U["lead"])
		with self.assertRaises(frappe.ValidationError):
			api.escalate_issue(doc.name, SP["B"])

	def test_32_cannot_escalate_into_secret(self):
		doc = self.issue(U["mem"], SP["A"], "pt no secret")
		as_user(U["lead"])
		with self.assertRaises(frappe.ValidationError):
			api.escalate_issue(doc.name, SP["S"])

	def test_33_notes_private_to_runners(self):
		as_user(U["lead"])
		m = frappe.get_doc({"doctype": "Pulse Meeting", "space": SP["A"], "scheduled_start": add_to_date(now_datetime(), days=40)}).insert()
		notes = frappe.get_doc({"doctype": "Pulse Meeting Notes", "meeting": m.name, "notes": "draft"}).insert()
		self.assertTrue(self.sees(U["lead"], notes))
		self.assertFalse(self.sees(U["mem"], notes))
		self.assertTrue(self.sees(U["mem"], m))
		as_user(U["mem"])
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc({"doctype": "Pulse Meeting Notes", "meeting": m.name, "notes": "x"}).insert()

	def test_34_rating_optional_and_own(self):
		as_user(U["lead"])
		m = frappe.get_doc({"doctype": "Pulse Meeting", "space": SP["A"], "scheduled_start": add_to_date(now_datetime(), days=41)}).insert()
		api.start_meeting(m.name)
		as_user(U["out"])
		with self.assertRaises(frappe.PermissionError):
			api.set_rating(m.name, 9)
		as_user(U["lead"])
		api.conclude_meeting(m.name)
		m.reload()
		self.assertEqual(m.average_rating, 0)

	def test_40_recurring_meetings_idempotent(self):
		frappe.db.set_value("Pulse Space", SP["B"], {"cadence": "Weekly", "meeting_weekday": "Wednesday", "meeting_time": "08:30:00", "schedule_ahead_days": 21})
		visibility.clear_cache()
		first_day, last_day = getdate(today()), add_days(getdate(today()), 21)
		wednesdays = {d for d in (add_days(first_day, n) for n in range(22)) if d.weekday() == 2}

		def days():
			starts = frappe.get_all(
				"Pulse Meeting",
				filters={"space": SP["B"], "status": ["!=", "Cancelled"], "scheduled_start": ["between", [first_day, add_days(last_day, 1)]]},
				pluck="scheduled_start",
			)
			return [getdate(d) for d in starts]

		scheduler.generate_meetings()
		once = days()
		scheduler.generate_meetings()
		twice = days()
		self.assertEqual(sorted(once), sorted(twice), "a second run creates nothing")
		self.assertTrue(wednesdays <= set(twice), "every Wednesday has a meeting")
		generated = [getdate(d) for d in frappe.get_all("Pulse Meeting", filters={"space": SP["B"], "auto_generated": 1}, pluck="scheduled_start")]
		self.assertEqual(len(generated), len(set(generated)), "no date is generated twice")
		self.assertTrue(all(d.weekday() == 2 for d in generated))
		frappe.db.set_value("Pulse Space", SP["B"], "cadence", "None")

	def test_41_digest_once_per_person(self):
		self.action(U["lead"], SP["A"], U["mem2"], "pt digest a", due_date=add_days(today(), -2))
		self.action(U["lead"], SP["A"], U["mem2"], "pt digest b", due_date=today())
		before = frappe.db.count("Email Queue Recipient", {"recipient": U["mem2"]})
		scheduler.daily_digest()
		after = frappe.db.count("Email Queue Recipient", {"recipient": U["mem2"]})
		self.assertEqual(after - before, 1)

	def test_50_lists_match_document_checks(self):
		"""Every Pulse record: list membership equals the document read check, for every test user."""
		for dt in CONTENT:
			for name in frappe.get_all(dt, pluck="name", limit=60):
				doc = frappe.get_doc(dt, name)
				for user in U.values():
					self.sees(user, doc)
