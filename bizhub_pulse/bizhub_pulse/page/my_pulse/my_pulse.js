// Copyright (c) 2026, NextTech BizHub and contributors
// License: MIT. See LICENSE
// My Pulse: my actions, my issues, my meetings.

frappe.pages["my-pulse"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("My Pulse"), single_column: true });
	page.set_primary_action(__("Refresh"), () => load());
	const $body = $(`<div style="padding:16px 0"></div>`).appendTo(page.main);
	const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
	const date = (d) => (d ? frappe.datetime.str_to_user(d).split(" ")[0] : "");

	function card(title, rows, empty) {
		const $c = $(`<div style="border:1px solid var(--border-color);border-radius:8px;padding:12px 16px;margin-bottom:12px">
			<h5 style="margin-top:0">${esc(title)}</h5></div>`);
		if (!rows.length) $c.append(`<div class="text-muted">${esc(empty)}</div>`);
		rows.forEach(($r) => $c.append($r));
		return $c;
	}
	function action_row(a, done_button) {
		const $r = $(`<div style="display:flex;justify-content:space-between;gap:8px;padding:6px 0;border-bottom:1px solid var(--border-color)">
			<a href="/app/pulse-action/${encodeURIComponent(a.name)}">${esc(a.title)}</a>
			<span class="text-muted">${esc(a.space)} · ${__("due")} ${date(a.due_date)}</span></div>`);
		if (done_button) {
			$(`<button class="btn btn-xs btn-default">${__("Done")}</button>`).appendTo($r).on("click", () => {
				frappe.prompt({ fieldname: "note", fieldtype: "Small Text", label: __("Completion note") }, (v) =>
					frappe.call("bizhub_pulse.api.complete_action", { action: a.name, completion_note: v.note }).then(load)
				);
			});
		}
		return $r;
	}

	function load() {
		frappe.call("bizhub_pulse.api.my_pulse").then((r) => {
			const d = r.message;
			$body.empty();
			$body.append(
				card(
					__("Priorities I own"),
					d.priorities.map((p) => $(`<div style="padding:6px 0"><a href="/app/pulse-priority/${encodeURIComponent(p.name)}">${esc(p.title)}</a>
						<span class="text-muted"> · ${esc(p.space)} · ${__(p.status)} · ${__("due")} ${date(p.due_date)}</span></div>`)),
					__("None.")
				)
			);
			$body.append(card(__("Overdue"), d.overdue.map((a) => action_row(a, true)), __("Nothing overdue.")));
			$body.append(card(__("Due"), d.due.map((a) => action_row(a, true)), __("Nothing due.")));
			$body.append(card(__("Done in the last 7 days"), d.done_recently.map((a) => action_row(a)), __("None.")));
			$body.append(card(__("Actions I assigned, still open"), d.assigned_by_me_open.map((a) => action_row(a)), __("None.")));
			$body.append(
				card(
					__("Issues I own"),
					d.issues.map((i) => $(`<div style="padding:6px 0"><a href="/app/pulse-issue/${encodeURIComponent(i.name)}">${esc(i.title)}</a>
						<span class="text-muted"> · ${esc(i.space)}</span></div>`)),
					__("None.")
				)
			);
			$body.append(
				card(
					__("Meetings"),
					d.meetings.map((m) => $(`<div style="padding:6px 0"><a href="/app/pulse-room/${encodeURIComponent(m.name)}">${esc(m.title)}</a>
						<span class="text-muted"> · ${__(m.status)}</span></div>`)),
					__("No upcoming meetings.")
				)
			);
		});
	}
	wrapper.pulse_load = load;
};

frappe.pages["my-pulse"].on_page_show = function (wrapper) {
	wrapper.pulse_load && wrapper.pulse_load();
};
