"""HTTP checks for BizHub Pulse against a RUNNING staging web server.

Not part of run-tests: it commits synthetic users, spaces and records, then
deletes them. Staging only.

    cd frappe-bench/sites
    ../env/bin/python ../apps/bizhub_pulse/bizhub_pulse/tests/http_checks.py \
        --site <staging-site> --url http://127.0.0.1:8000

Prints one line per check and a JSON summary; exits non-zero on any failure.
"""

import argparse
import json
import secrets
import sys

import requests

import frappe
from frappe.utils import add_to_date, now_datetime

DOM = "pulse-http.invalid"
MARKER = "zz-pulse-http-7731"
KEYS = ("lead", "mem", "mem2", "out", "secret")


def setup(site):
	frappe.init(site=site, sites_path=".")
	frappe.connect()
	frappe.set_user("Administrator")
	frappe.flags.mute_emails = True
	from frappe.utils.password import update_password

	password = secrets.token_urlsafe(16)
	users = {}
	for key in KEYS:
		email = f"{key}@{DOM}"
		if not frappe.db.exists("User", email):
			u = frappe.get_doc({"doctype": "User", "email": email, "first_name": key, "send_welcome_email": 0, "user_type": "System User"})
			u.flags.no_welcome_mail = True
			u.insert(ignore_permissions=True)
			u.add_roles("Pulse User")
		update_password(email, password)
		users[key] = email

	def space(name, vis, members):
		if not frappe.db.exists("Pulse Space", name):
			frappe.get_doc({"doctype": "Pulse Space", "space_name": name, "space_type": "Team", "visibility": vis,
				"default_template": "Weekly Team Meeting",
				"members": [{"user": users[u], "member_role": r} for u, r in members]}).insert(ignore_permissions=True)
		return name

	a = space("PH Team A", "Private", [("lead", "Leader"), ("mem", "Member"), ("mem2", "Member")])
	s = space("PH Secret " + MARKER, "Secret", [("secret", "Leader")])
	frappe.set_user(users["mem"])
	issue = frappe.get_doc({"doctype": "Pulse Issue", "space": a, "title": "issue " + MARKER}).insert()
	frappe.set_user(users["lead"])
	restricted = frappe.get_doc({"doctype": "Pulse Action", "space": a, "title": "restricted " + MARKER,
		"assigned_to": users["mem"], "visibility": "Restricted"}).insert()
	meeting = frappe.get_doc({"doctype": "Pulse Meeting", "space": a, "scheduled_start": add_to_date(now_datetime(), days=3)}).insert()
	notes = frappe.get_doc({"doctype": "Pulse Meeting Notes", "meeting": meeting.name, "notes": "notes " + MARKER}).insert()
	frappe.set_user("Administrator")
	frappe.db.commit()
	return password, users, {"A": a, "S": s, "issue": issue.name, "restricted": restricted.name, "meeting": meeting.name, "notes": notes.name}


def cleanup(users):
	frappe.set_user("Administrator")
	for dt in ("Pulse Meeting Notes", "Pulse Action", "Pulse Issue", "Pulse Decision", "Pulse Headline", "Pulse Message", "Pulse Meeting"):
		for name in frappe.get_all(dt, filters={"owner": ["in", list(users.values())]}, pluck="name"):
			frappe.delete_doc(dt, name, force=True, ignore_permissions=True)
	for name in frappe.get_all("Pulse Space", filters={"space_name": ["like", "PH %"]}, pluck="name"):
		for dt in ("Pulse Meeting",):
			for m in frappe.get_all(dt, filters={"space": name}, pluck="name"):
				frappe.delete_doc(dt, m, force=True, ignore_permissions=True)
		frappe.delete_doc("Pulse Space", name, force=True, ignore_permissions=True)
	for email in users.values():
		frappe.delete_doc("User", email, force=True, ignore_permissions=True)
	frappe.db.commit()


def session(url, user, password):
	s = requests.Session()
	r = s.post(f"{url}/api/method/login", data={"usr": user, "pwd": password})
	r.raise_for_status()
	return s


def main():
	p = argparse.ArgumentParser()
	p.add_argument("--site", required=True)
	p.add_argument("--url", required=True)
	args = p.parse_args()
	url = args.url.rstrip("/")
	password, users, ids = setup(args.site)
	S = {k: session(url, users[k], password) for k in KEYS}
	results = []

	def check(name, ok):
		results.append((name, bool(ok)))
		print(("PASS " if ok else "FAIL ") + name)

	def leaked(resp):
		return MARKER in resp.text

	try:
		r = S["out"].get(f"{url}/api/resource/Pulse Issue/{ids['issue']}")
		check("outsider cannot read a team issue (403)", r.status_code == 403 and not leaked(r))
		r = S["out"].get(f"{url}/api/resource/Pulse Issue", params={"fields": json.dumps(["name", "title"]), "limit_page_length": 0})
		check("outsider's issue list has no team issue", r.ok and not leaked(r))
		r = S["mem2"].get(f"{url}/api/resource/Pulse Action/{ids['restricted']}")
		check("member cannot read another's Restricted action (403)", r.status_code == 403 and not leaked(r))
		r = S["mem2"].post(f"{url}/api/method/frappe.desk.reportview.get", data={"doctype": "Pulse Action", "fields": json.dumps(["`tabPulse Action`.`title`"])})
		check("report view hides the Restricted action", r.ok and not leaked(r))
		r = S["mem2"].get(f"{url}/api/method/frappe.client.get_count", params={"doctype": "Pulse Action", "filters": json.dumps({"visibility": "Restricted"})})
		check("count excludes the Restricted action", r.ok and r.json().get("message") == 0)
		r = S["mem"].get(f"{url}/api/resource/Pulse Action/{ids['restricted']}")
		check("owner reads their Restricted action (positive control)", r.ok and leaked(r))
		r = S["lead"].get(f"{url}/api/resource/Pulse Space/{ids['S']}")
		check("non-member cannot read a Secret space (403)", r.status_code == 403)
		r = S["out"].post(f"{url}/api/method/frappe.desk.search.search_link", data={"doctype": "Pulse Space", "txt": MARKER})
		check("Secret space absent from link search", r.ok and not leaked(r))
		r = S["out"].post(f"{url}/api/method/bizhub_pulse.api.get_meeting", data={"meeting": ids["meeting"]})
		check("outsider cannot load the meeting screen", r.status_code == 403)
		r = S["mem"].post(f"{url}/api/method/bizhub_pulse.api.start_meeting", data={"meeting": ids["meeting"]})
		check("member cannot start the meeting", r.status_code == 403)
		r = S["mem"].get(f"{url}/api/resource/Pulse Meeting Notes/{ids['notes']}")
		check("member cannot read draft notes (403)", r.status_code == 403 and not leaked(r))
		r = S["mem"].put(f"{url}/api/resource/Pulse Issue/{ids['issue']}", data={"data": json.dumps({"raised_by": users["lead"]})})
		check("raised_by cannot be changed over REST", not r.ok)
		r = S["mem"].post(f"{url}/api/resource/Pulse Action", data={"data": json.dumps({
			"space": ids["A"], "title": "forged", "assigned_to": users["mem2"], "assigned_by": users["lead"]})})
		stored = r.ok and r.json()["data"]["assigned_by"]
		check("forged assigned_by is replaced by the real creator", stored == users["mem"])
		r = S["mem"].put(f"{url}/api/resource/Pulse Issue/{ids['issue']}", data={"data": json.dumps({"space": ids["S"]})})
		check("an issue cannot be moved into a Secret space", not r.ok)
		r = S["mem"].post(f"{url}/api/method/frappe.share.add", data={"doctype": "Pulse Issue", "name": ids["issue"], "user": users["out"], "read": 1})
		check("sharing a Pulse record is refused", not r.ok)
		r = S["out"].post(f"{url}/api/resource/Pulse Issue", data={"data": json.dumps({"space": ids["A"], "title": "intruder"})})
		check("outsider cannot add an issue to the space", r.status_code == 403)
		r = S["out"].post(f"{url}/api/method/bizhub_pulse.api.add_issue", data={"space": ids["A"], "title": "intruder"})
		check("outsider cannot add an issue through the API", r.status_code == 403)
		r = S["mem"].post(f"{url}/api/method/bizhub_pulse.api.escalate_issue", data={"issue": ids["issue"], "target_space": ids["S"]})
		check("cannot escalate into a Secret space", not r.ok)
		r = S["out"].post(f"{url}/api/method/frappe.desk.listview.get_group_by_count", data={"doctype": "Pulse Issue", "current_filters": "[]", "field": "owner"})
		check("sidebar counts reveal nothing to an outsider", r.ok and users["mem"] not in r.text)
	finally:
		cleanup(users)
		frappe.destroy()
	failed = [n for n, ok in results if not ok]
	print(json.dumps({"total": len(results), "passed": len(results) - len(failed), "failed": failed}))
	sys.exit(1 if failed else 0)


if __name__ == "__main__":
	main()
