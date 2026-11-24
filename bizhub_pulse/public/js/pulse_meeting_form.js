// Copyright (c) 2026, NextTech BizHub and contributors
// License: MIT. See LICENSE
frappe.ui.form.on("Pulse Meeting", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Open meeting screen"), () => frappe.set_route("pulse-room", frm.doc.name)).addClass("btn-primary");
		const field = frm.get_field("follow_up_html");
		if (field && window.pulse_followup) window.pulse_followup(field.$wrapper, frm.doc.name);
	},
});
