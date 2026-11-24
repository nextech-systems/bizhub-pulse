// Copyright (c) 2026, NextTech BizHub and contributors
// License: MIT. See LICENSE
// Adds "Pulse" buttons and a sidebar list of open Pulse items to the DocTypes chosen in Pulse Settings.
// v15 can load app scripts before jQuery, so wait for the page before using $.
(function (start) {
	if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
	else start();
})(function () {
jQuery(document).on("form-refresh", function (e, frm) {
	const allowed = (frappe.boot && frappe.boot.pulse_linkable) || [];
	if (!frm || frm.is_new() || !allowed.includes(frm.doctype)) return;
	const esc = frappe.utils.escape_html;

	function create(kind) {
		frappe.call("bizhub_pulse.api.contribute_spaces").then((r) => {
			const spaces = r.message || [];
			if (!spaces.length) {
				frappe.msgprint(__("You are not a contributing member of any Pulse space."));
				return;
			}
			const fields = [
				{ fieldname: "space", fieldtype: "Select", options: spaces.join("\n"), label: __("Space"), reqd: 1, default: spaces[0] },
				{ fieldname: "title", fieldtype: "Data", label: kind === "issue" ? __("Issue") : __("Action"), reqd: 1, default: `${frm.doctype} ${frm.doc.name}: ` },
			];
			if (kind === "action") {
				fields.push({ fieldname: "assigned_to", fieldtype: "Link", options: "User", label: __("Owner"), reqd: 1 });
				fields.push({ fieldname: "due_date", fieldtype: "Date", label: __("Due") });
			}
			fields.push({ fieldname: "visibility", fieldtype: "Select", options: "Team\nRestricted", default: "Team", label: __("Visibility") });
			frappe.prompt(fields, (v) => {
				frappe
					.call(`bizhub_pulse.api.${kind === "issue" ? "add_issue" : "add_action"}`, {
						...v,
						reference_doctype: frm.doctype,
						reference_name: frm.doc.name,
					})
					.then(() => {
						frappe.show_alert({ message: __("Added to {0}", [v.space]), indicator: "green" });
						show_linked();
					});
			}, kind === "issue" ? __("Raise Pulse issue") : __("Add Pulse action"));
		});
	}

	frm.add_custom_button(__("Raise issue"), () => create("issue"), __("Pulse"));
	frm.add_custom_button(__("Add action"), () => create("action"), __("Pulse"));

	function show_linked() {
		frappe.call({ method: "bizhub_pulse.api.linked_items", args: { doctype: frm.doctype, name: frm.doc.name }, quiet: true }).then((r) => {
			const d = r.message || { issues: [], actions: [] };
			frm.sidebar && frm.sidebar.sidebar && frm.sidebar.sidebar.find(".pulse-linked").remove();
			if (!d.issues.length && !d.actions.length) return;
			const items = d.issues
				.map((i) => `<li><a href="/app/pulse-issue/${encodeURIComponent(i.name)}">${esc(i.title)}</a></li>`)
				.concat(d.actions.map((a) => `<li><a href="/app/pulse-action/${encodeURIComponent(a.name)}">${esc(a.title)}</a></li>`));
			const $box = $(`<div class="pulse-linked sidebar-section"><div class="sidebar-label">${__("Open in Pulse")}</div><ul class="list-unstyled">${items.join("")}</ul></div>`);
			frm.sidebar && frm.sidebar.sidebar && frm.sidebar.sidebar.append($box);
		});
	}
	show_linked();
});
});
