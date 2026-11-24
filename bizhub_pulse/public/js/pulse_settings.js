// Copyright (c) 2026, NextTech BizHub and contributors
// License: MIT. See LICENSE
frappe.ui.form.on("Pulse Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Check reporting lines"), () => {
			frappe.call("bizhub_pulse.bizhub_pulse.doctype.pulse_settings.pulse_settings.employees_without_manager").then((r) => {
				const rows = r.message || [];
				frappe.msgprint({
					title: __("Active employees without a manager"),
					message: rows.length
						? `<p>${__("{0} employees have no Reports To. Person spaces and Restricted actions need it.", [rows.length])}</p><ul>` +
						  rows.map((e) => `<li>${frappe.utils.escape_html(e.employee_name || e.name)}</li>`).join("") + "</ul>"
						: __("Every active employee with a user has a manager."),
				});
			});
		});
	},
});
