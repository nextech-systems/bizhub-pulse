// Copyright (c) 2026, NextTech BizHub and contributors
// License: MIT. See LICENSE
// The live Follow-up panel for a meeting, shared by the meeting form and the meeting screen.
window.pulse_followup = function ($el, meeting) {
	const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
	const day = (d) => (d ? frappe.datetime.str_to_user(d).split(" ")[0] : "");
	$el.html(`<div class="text-muted">${__("Loading follow-up...")}</div>`);
	return frappe.call({ method: "bizhub_pulse.api.meeting_followup", args: { meeting }, quiet: true }).then((r) => {
		const d = r.message;
		const s = d.stats;
		const pct = s.actions ? Math.round((100 * s.done) / s.actions) : 0;
		const pill = (text, colour) => `<span class="indicator-pill ${colour}" style="margin-left:6px">${esc(text)}</span>`;
		const box = (title, inner) =>
			`<div style="border:1px solid var(--border-color);border-radius:8px;padding:12px 16px;margin-bottom:12px">
				<div style="font-weight:600;margin-bottom:8px">${title}</div>${inner}</div>`;
		const row = (left, right) =>
			`<div style="display:flex;justify-content:space-between;gap:12px;padding:6px 0;border-bottom:1px solid var(--border-color)">
				<span>${left}</span><span style="white-space:nowrap">${right}</span></div>`;
		const statusPill = (a) =>
			a.overdue ? pill(__("Overdue"), "red")
			: a.status === "Done" ? pill(a.verified_by ? __("Done, verified") : __("Done"), "green")
			: a.status === "Not Done" ? pill(__("Not done"), "orange")
			: a.status === "Cancelled" ? pill(__("Cancelled"), "gray")
			: pill(__("Open"), "blue");
		let html = `<div style="display:flex;gap:24px;flex-wrap:wrap;margin-bottom:12px">
			<div><div style="font-size:22px;font-weight:600">${s.done} / ${s.actions}</div><div class="text-muted">${__("actions done")} (${pct}%)</div></div>
			<div><div style="font-size:22px;font-weight:600;color:${s.overdue ? "var(--red-600)" : "inherit"}">${s.overdue}</div><div class="text-muted">${__("overdue")}</div></div>
			<div><div style="font-size:22px;font-weight:600">${s.verified}</div><div class="text-muted">${__("verified")}</div></div>
			<div><div style="font-size:22px;font-weight:600">${s.issues - s.issues_open} / ${s.issues}</div><div class="text-muted">${__("issues closed")}</div></div>
		</div>
		<div style="height:6px;background:var(--subtle-fg);border-radius:3px;margin-bottom:16px"><div style="height:6px;width:${pct}%;background:var(--green-500);border-radius:3px"></div></div>`;
		html += box(
			__("Actions from this meeting"),
			d.actions.length
				? d.actions.map((a) => row(
					`<a href="/app/pulse-action/${encodeURIComponent(a.name)}">${esc(a.title)}</a><br><span class="text-muted">${esc(a.owner_name)}${a.carried_over ? " · " + __("carried {0}×", [a.carried_over]) : ""}${a.visibility === "Restricted" ? " · " + __("Restricted") : ""}</span>`,
					`${__("due")} ${day(a.due_date)}${statusPill(a)}`)).join("")
				: `<div class="text-muted">${__("No actions.")}</div>`
		);
		html += box(
			__("Issues raised or settled here"),
			d.issues.length
				? d.issues.map((i) => row(
					`<a href="/app/pulse-issue/${encodeURIComponent(i.name)}">${esc(i.title)}</a>${i.owner_name ? `<br><span class="text-muted">${esc(i.owner_name)}</span>` : ""}`,
					i.status === "Open" ? pill(__("Open"), "blue") : pill(__(i.status) + (i.escalated_to ? " → " + i.escalated_to : ""), i.status === "Dropped" ? "gray" : "green"))).join("")
				: `<div class="text-muted">${__("None.")}</div>`
		);
		html += box(
			__("Decisions"),
			d.decisions.length
				? d.decisions.map((x) => row(`<a href="/app/pulse-decision/${encodeURIComponent(x.name)}">${esc(x.decision)}</a>`,
					`${x.review_date ? __("review") + " " + day(x.review_date) : ""}${x.status !== "Active" ? pill(__(x.status), "gray") : ""}`)).join("")
				: `<div class="text-muted">${__("None.")}</div>`
		);
		$el.html(html);
		return d;
	});
};
