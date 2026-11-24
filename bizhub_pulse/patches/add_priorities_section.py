# Copyright (c) 2026, NextTech BizHub and contributors
# License: MIT. See LICENSE
"""0.2.0: add a Priorities section to the two weekly starter templates, if missing.

Templates people have edited keep their own choices: the section is added only
when the template still has no Priorities section, and Issue solving gives up
the 5 minutes so the meeting stays the same length.
"""

import frappe

GUIDANCE = {
	"Weekly Team Meeting": "Each owner: on track or off track. Off track goes to Issues, no discussion here.",
	"Weekly Leadership Meeting": "Company and team priorities: on track or off track.",
}


def execute():
	for name, guidance in GUIDANCE.items():
		if not frappe.db.exists("Pulse Meeting Template", name):
			continue
		doc = frappe.get_doc("Pulse Meeting Template", name)
		if any(r.section_type == "Priorities" for r in doc.sections):
			continue
		rows = [r.as_dict() for r in doc.sections]
		after = next((i for i, r in enumerate(rows) if r.section_type == "Scorecard"), 0)
		rows.insert(after + 1, {"section_type": "Priorities", "title": "Priorities", "minutes": 5, "guidance": guidance})
		for r in rows:
			if r["section_type"] == "Issue Solving" and r["minutes"] > 10:
				r["minutes"] -= 5
				break
		doc.set("sections", [])
		for r in rows:
			doc.append("sections", {k: r.get(k) for k in ("section_type", "title", "minutes", "guidance")})
		doc.flags.ignore_permissions = True
		doc.save()
