// Copyright (c) 2026, NextTech BizHub and contributors
// License: MIT. See LICENSE
// The meeting screen: one page, timed sections, everything filtered by the server.

const PM_API = "bizhub_pulse.api.";
const esc = (v) => frappe.utils.escape_html(v == null ? "" : String(v));
const fmt_date = (d) => (d ? frappe.datetime.str_to_user(d).split(" ")[0] : "");
const user_name = (u) => esc(frappe.user.full_name(u) || u);

frappe.pages["pulse-room"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({ parent: wrapper, title: __("Pulse Meeting"), single_column: true });
	wrapper.pulse = new PulseMeeting(page, wrapper);
};

frappe.pages["pulse-room"].on_page_show = function (wrapper) {
	const name = frappe.get_route()[1];
	if (!name) {
		frappe.set_route("List", "Pulse Meeting");
		return;
	}
	wrapper.pulse.load(decodeURIComponent(name));
};

class PulseMeeting {
	constructor(page, wrapper) {
		this.page = page;
		this.$body = $(`<div class="pulse-meeting"></div>`).appendTo(page.main);
		this.viewing = null;
		this.clock_offset = 0;
		this.add_styles();
		setInterval(() => this.tick(), 1000);
		this.last_tangent = 0;
		frappe.realtime.on("pulse_tangent", (d) => {
			if (d && d.meeting === this.name && frappe.get_route()[0] === "pulse-room") this.show_tangent(d);
		});
		frappe.realtime.on("pulse_dictation", (d) => {
			if (d && d.meeting === this.name && this.s) {
				this.s.dictation = d.state;
				this.show_dictation_banner();
			}
		});
		// Leaving the meeting (another page or another meeting) always stops this browser's dictation.
		frappe.router.on("change", () => {
			const r = frappe.get_route();
			if (this.dictating && (r[0] !== "pulse-room" || decodeURIComponent(r[1] || "") !== this.dictating)) this.stop_dictation();
		});
		window.addEventListener("beforeunload", () => this.dictating && this.stop_dictation(true));
	}

	subscribe(name) {
		// Join the meeting's live room (Frappe checks read access) so tangent alerts reach this screen.
		const rt = frappe.realtime.doc_subscribe ? frappe.realtime : frappe.socketio;
		if (!rt || !rt.doc_subscribe || this.subscribed === name) return;
		if (this.subscribed && rt.doc_unsubscribe) rt.doc_unsubscribe("Pulse Meeting", this.subscribed);
		this.subscribed = name;
		rt.doc_subscribe("Pulse Meeting", name);
		// Frappe throttles subscriptions to one a second; repeat once in case this one was dropped.
		setTimeout(() => this.subscribed === name && rt.doc_subscribe("Pulse Meeting", name), 1500);
	}

	add_styles() {
		if (document.getElementById("pulse-meeting-style")) return;
		$(`<style id="pulse-meeting-style">
			.pulse-meeting { display: grid; grid-template-columns: 240px 1fr; gap: 24px; padding: 16px 0; }
			.pulse-meeting .pm-nav .pm-sec { padding: 8px 12px; border-radius: 8px; cursor: pointer; margin-bottom: 4px;
				display: flex; justify-content: space-between; gap: 8px; border: 1px solid transparent; }
			.pulse-meeting .pm-nav .pm-sec:hover { background: var(--subtle-fg); }
			.pulse-meeting .pm-nav .pm-sec.viewing { border-color: var(--border-color); background: var(--subtle-accent); }
			.pulse-meeting .pm-nav .pm-sec.current { font-weight: 600; }
			.pulse-meeting .pm-nav .pm-time { color: var(--text-muted); font-variant-numeric: tabular-nums; white-space: nowrap; }
			.pulse-meeting .pm-nav .over { color: var(--red-600); }
			.pulse-meeting .pm-guidance { color: var(--text-muted); margin-bottom: 16px; }
			.pulse-meeting .pm-card { border: 1px solid var(--border-color); border-radius: 8px; padding: 12px 16px; margin-bottom: 12px; }
			.pulse-meeting .pm-row { display: flex; align-items: center; gap: 8px; justify-content: space-between; flex-wrap: wrap;
				padding: 8px 0; border-bottom: 1px solid var(--border-color); }
			.pulse-meeting .pm-row:last-child { border-bottom: 0; }
			.pulse-meeting .pm-muted { color: var(--text-muted); font-size: var(--text-sm); }
			.pulse-meeting .pm-actions { display: flex; gap: 6px; flex-wrap: wrap; }
			.pulse-meeting h5 { margin: 16px 0 8px; }
			.pm-dictation { position: sticky; top: 60px; z-index: 19; background: #b42318; color: #fff; border-radius: 10px;
				padding: 10px 16px; margin: 8px 0; display: flex; gap: 12px; align-items: center; justify-content: space-between; flex-wrap: wrap; }
			.pm-dictation .pm-dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; background: #fff; margin-right: 8px;
				animation: pm-blink 1.2s infinite; }
			@keyframes pm-blink { 50% { opacity: .2; } }
			.pm-dictate-bar { display: flex; gap: 8px; align-items: center; margin: 4px 0 8px; flex-wrap: wrap; }
			.pm-dictate-bar .btn-danger { background: #b42318; color: #fff; }
			.pm-interim { color: var(--text-muted); font-style: italic; min-height: 1.4em; margin-top: 4px; }
			.pm-tangent-btn { background: var(--orange-500, #f97316) !important; color: #fff !important; font-weight: 600; }
			.pm-tangent { position: sticky; top: 60px; z-index: 20; display: flex; gap: 16px; align-items: center; justify-content: space-between;
				flex-wrap: wrap; background: var(--orange-500, #f97316); color: #fff; border-radius: 10px; padding: 14px 18px; margin: 8px 0;
				box-shadow: 0 6px 20px rgba(0,0,0,.25); animation: pm-pulse 0.6s ease-in-out 3; }
			.pm-tangent .pm-tangent-title { font-size: 20px; font-weight: 700; }
			.pm-tangent .pm-tangent-sub { font-size: 15px; }
			.pm-tangent .btn { background: #fff; color: #9a3412; border: 0; }
			@keyframes pm-pulse { 0%,100% { transform: scale(1); } 50% { transform: scale(1.02); } }
			@media (max-width: 768px) { .pulse-meeting { grid-template-columns: 1fr; } }
		</style>`).appendTo("head");
	}

	async load(name) {
		this.name = name;
		this.subscribe(name);
		const r = await frappe.call({ method: PM_API + "get_meeting", args: { meeting: name } });
		this.set_state(r.message);
	}

	set_state(state) {
		this.s = state;
		this.m = state.meeting;
		this.clock_offset = moment(state.server_time).diff(moment());
		if (!this.viewing || this.viewing > this.m.sections.length) {
			this.viewing = this.m.current_section || 1;
		}
		this.render();
	}

	async call(method, args, reload = true) {
		// A native Promise: v15 dialogs call .finally() on what a handler returns.
		const r = await frappe.call({ method: PM_API + method, args, freeze: true });
		if (reload) await this.load(this.name);
		return r && r.message;
	}

	// ------------------------------------------------------------- layout

	render() {
		// Keep anything typed in the minutes box before the screen redraws.
		if (this.flush_minutes) {
			this.flush_minutes();
			this.flush_minutes = null;
		}
		const m = this.m;
		this.page.set_title(esc(m.title));
		this.page.set_indicator(__(m.status), { Scheduled: "blue", "In Progress": "orange", Concluded: "yellow", Published: "green", Cancelled: "red" }[m.status]);
		this.page.clear_actions();
		this.page.clear_inner_toolbar();
		if (this.s.can_run) {
			if (m.status === "Scheduled") this.page.set_primary_action(__("Start meeting"), () => this.call("start_meeting", { meeting: this.name }));
			if (m.status === "In Progress") this.page.set_primary_action(__("Conclude meeting"), () => this.conclude());
			if (m.status === "Concluded") this.page.set_primary_action(__("Review and publish"), () => this.publish_dialog());
		}
		if (window.bizpulse_video) {
			const meeting = this.name, state = this.s;
			window.bizpulse_video.controls(meeting,
				(label, action) => this.page.add_inner_button(label, action, __("Video")),
				() => this.name === meeting && this.s === state);
		}
		if (m.join_url) this.page.add_inner_button(__("Join online"), () => window.open(m.join_url, "_blank", "noopener"));
		if (m.status === "In Progress") {
			const n = m.tangent_count ? ` (${m.tangent_count})` : "";
			this.page.add_inner_button("↩ " + __("Tangent") + n, () => this.tangent()).addClass("pm-tangent-btn")
				.attr("title", __("The discussion has gone off topic. Everyone in the meeting sees this."));
		}
		this.page.add_inner_button(__("Add issue"), () => this.issue_dialog());
		setTimeout(() => this.show_dictation_banner(), 0);
		if (this.s.can_run && m.status !== "Published" && m.status !== "Cancelled") {
			this.page.add_inner_button(__("Minutes"), () => this.minutes_dialog());
		}
		if (m.status !== "Published") {
			this.page.add_inner_button(__("Follow-up"), () => this.followup_dialog());
		}
		this.page.add_inner_button(__("Open record"), () => frappe.set_route("Form", "Pulse Meeting", this.name));

		this.$body.empty();
		const $nav = $(`<div class="pm-nav"></div>`).appendTo(this.$body);
		m.sections.forEach((sec, i) => {
			const idx = i + 1;
			const $s = $(`<div class="pm-sec">
				<span>${esc(sec.title)}</span>
				<span class="pm-time" data-idx="${idx}"></span>
			</div>`).appendTo($nav);
			$s.toggleClass("viewing", idx === this.viewing).toggleClass("current", idx === m.current_section);
			$s.on("click", () => this.select_section(idx));
		});
		$nav.append(`<div class="pm-muted" style="margin-top:12px">${__("Space")}: ${esc(m.space)}<br>
			${__("Facilitator")}: ${m.facilitator ? user_name(m.facilitator) : "–"}<br>
			${__("Secretary")}: ${m.secretary ? user_name(m.secretary) : "–"}</div>`);
		this.$main = $(`<div class="pm-main"></div>`).appendTo(this.$body);
		if (m.status === "Published") {
			this.$main.append(`<h4>${__("Follow-up")}</h4>`);
			const $f = $(`<div></div>`).appendTo(this.$main);
			if (window.pulse_followup) window.pulse_followup($f, this.name);
			this.$main.append(`<h4 style="margin-top:16px">${__("Published summary and minutes")}</h4><div class="pm-card">${m.summary || ""}</div>`);
			return;
		}
		if (m.status === "Concluded") {
			const $n = $(`<div class="pm-card" style="border-color: var(--orange-500, #f97316)">
				<b>${__("The summary and minutes have not been emailed yet.")}</b>
				<div class="pm-muted">${this.s.can_run
					? __("Check the minutes, then send them to the team. Each person also gets their own Pulse list.")
					: __("The facilitator or secretary sends them after checking the minutes.")}</div></div>`).appendTo(this.$main);
			if (this.s.can_run) {
				$(`<button class="btn btn-primary btn-sm" style="margin-top:8px">${__("Review and publish")}</button>`)
					.appendTo($n).on("click", () => this.publish_dialog());
			}
		}
		this.render_section();
		this.render_minutes_box();
		this.tick();
	}

	// ------------------------------------------------------------- tangent

	async tangent() {
		const r = await frappe.call({ method: PM_API + "call_tangent", args: { meeting: this.name } });
		const d = r && r.message;
		if (!d) return;
		if (d.sent) {
			this.show_tangent({ meeting: this.name, by: frappe.session.user, by_name: frappe.user.full_name(frappe.session.user),
				section: d.section, count: d.tangent_count });
		} else if (d.reason === "already") {
			frappe.show_alert({ message: __("A tangent was just called."), indicator: "orange" });
		} else {
			frappe.show_alert({ message: __("You called a tangent a moment ago."), indicator: "orange" });
		}
	}

	show_tangent(d) {
		// The caller sees it at once; everyone else through the live room. Show each tangent once.
		if (d.count && d.count <= this.last_tangent) return;
		this.last_tangent = d.count || this.last_tangent;
		if (this.m) this.m.tangent_count = d.count || this.m.tangent_count;
		$(this.page.main).find(".pm-tangent").remove();
		clearTimeout(this.tangent_timer);
		const who = d.by === frappe.session.user ? __("You") : esc(d.by_name || d.by);
		const $b = $(`<div class="pm-tangent" role="alert">
			<div><div class="pm-tangent-title">↩ ${__("Tangent!")}</div>
			<div class="pm-tangent-sub">${who} ${__("called it: we have drifted off topic.")}
			${d.section ? __("Back to") + ": <b>" + esc(d.section) + "</b>" : ""}</div></div>
			<div class="pm-actions"></div></div>`);
		const $a = $b.find(".pm-actions");
		if (this.s && this.s.can_run) {
			$(`<button class="btn btn-sm">${__("Park as issue")}</button>`).appendTo($a)
				.on("click", () => { $b.remove(); this.issue_dialog({ title: __("Parked: ") }); });
		}
		$(`<button class="btn btn-sm">${__("Back on track")}</button>`).appendTo($a).on("click", () => $b.remove());
		$b.prependTo(this.page.main);
		this.tangent_timer = setTimeout(() => $b.fadeOut(400, () => $b.remove()), 12000);
		const $btn = this.page.inner_toolbar && this.page.inner_toolbar.find(".pm-tangent-btn");
		if ($btn && $btn.length && d.count) $btn.text("↩ " + __("Tangent") + ` (${d.count})`);
	}

	select_section(idx) {
		if (this.flush_minutes) this.flush_minutes();
		this.flush_minutes = null;
		this.viewing = idx;
		if (this.s.can_run && this.m.status === "In Progress" && idx !== this.m.current_section) {
			frappe.call({ method: PM_API + "goto_section", args: { meeting: this.name, index: idx } }).then((r) => {
				this.m.current_section = r.message.current_section;
				this.m.sections = r.message.sections;
				this.render();
			});
		} else {
			this.render();
		}
	}

	tick() {
		if (!this.m) return;
		const now = moment().add(this.clock_offset, "ms");
		this.m.sections.forEach((sec, i) => {
			let secs = sec.actual_seconds || 0;
			if (sec.started_at) secs += Math.max(0, now.diff(moment(sec.started_at), "seconds"));
			const planned = (sec.planned_minutes || 0) * 60;
			const label = secs || sec.started_at ? `${Math.floor(secs / 60)}:${String(secs % 60).padStart(2, "0")} / ${sec.planned_minutes}m` : `${sec.planned_minutes}m`;
			const $t = this.$body.find(`.pm-time[data-idx="${i + 1}"]`);
			$t.text(label).toggleClass("over", planned > 0 && secs > planned);
		});
	}

	render_section() {
		const sec = this.m.sections[this.viewing - 1];
		if (!sec) return;
		this.$main.append(`<h4>${esc(sec.title)}</h4>`);
		if (sec.guidance) this.$main.append(`<div class="pm-guidance">${esc(sec.guidance)}</div>`);
		const fn = {
			Opening: "render_opening",
			Scorecard: "render_scorecard",
			Priorities: "render_priorities",
			Headlines: "render_headlines",
			"Action Review": "render_action_review",
			"Issue Solving": "render_issues",
			Conclusion: "render_conclusion",
		}[sec.section_type];
		if (fn) this[fn]();
	}

	running() {
		return this.s.can_run && this.m.status === "In Progress";
	}

	// ------------------------------------------------------------- sections

	render_opening() {
		const $c = $(`<div class="pm-card"></div>`).appendTo(this.$main);
		$c.append(`<h5>${__("Attendance")}</h5>`);
		this.m.attendees.forEach((a) => {
			const $r = $(`<div class="pm-row"><span>${user_name(a.user)}</span><span class="pm-actions"></span></div>`).appendTo($c);
			if (this.s.can_run && ["Scheduled", "In Progress", "Concluded"].includes(this.m.status)) {
				["Present", "Absent", "Excused"].forEach((st) => {
					const $b = $(`<button class="btn btn-xs ${a.attendance === st ? "btn-primary" : "btn-default"}">${__(st)}</button>`);
					$b.on("click", () => this.call("set_attendance", { meeting: this.name, user: a.user, attendance: st }));
					$r.find(".pm-actions").append($b);
				});
			} else {
				$r.find(".pm-actions").text(__(a.attendance));
			}
		});
	}

	render_scorecard() {
		const $c = $(`<div class="pm-card">
			<p>${__("Each owner reports their numbers as on track or off track. Anything off track becomes an issue for Issue solving.")}</p>
			<p class="pm-muted">${__("Numbers calculated from ERPNext arrive in Stage 2.")}</p>
		</div>`).appendTo(this.$main);
		if (this.s.can_contribute) {
			$(`<button class="btn btn-default btn-sm">${__("Off track: add as issue")}</button>`)
				.appendTo($c)
				.on("click", () => this.issue_dialog({ title: __("Off track: ") }));
		}
	}

	render_priorities() {
		const $c = $(`<div class="pm-card"></div>`).appendTo(this.$main);
		const list = this.s.priorities || [];
		if (!list.length) $c.append(`<div class="pm-muted">${__("No open priorities in this space.")}</div>`);
		list.forEach((p) => {
			const red = p.status === "Off Track";
			let progress = "";
			if (p.kind === "Measured") {
				const unit = esc(p.unit || "");
				progress = `${esc(p.measure_name || "")}: ${p.current_value != null ? esc(p.current_value) + unit : "–"} ${__("now")}, ${__("target")} ${esc(p.target_value)}${unit}` +
					(p.start_value != null ? ` (${__("from")} ${esc(p.start_value)}${unit})` : "") +
					(p.current_as_of ? ` · ${__("as of")} ${fmt_date(p.current_as_of)}` : "");
			} else {
				const next = p.next_milestone;
				progress = `${p.milestones_done} ${__("of")} ${p.milestones.length} ${__("milestones done")}` +
					(next ? ` · ${__("next")}: ${esc(next.milestone)}, ${fmt_date(next.due_date)}${next.milestone_owner ? " (" + user_name(next.milestone_owner) + ")" : ""}` : "");
				if (p.overdue.length) progress += ` · <span style="color:var(--red-600)">${__("overdue")}: ${p.overdue.map(esc).join(", ")}</span>`;
			}
			const $r = $(`<div class="pm-row" style="align-items:flex-start">
				<span style="flex:1;min-width:260px">
					<strong>${esc(p.title)}</strong> <span class="indicator-pill ${red ? "red" : "green"}">${__(p.status)}</span><br>
					<span class="pm-muted">${user_name(p.priority_owner)} · ${__("due")} ${fmt_date(p.due_date)}${p.visibility === "Restricted" ? " · " + __("Restricted") : ""}</span><br>
					<span>${progress}</span>
					${p.support_needed ? `<br><span class="pm-muted">${__("Support needed")}: ${esc(p.support_needed)}</span>` : ""}
					${p.open_actions.length ? `<br><span class="pm-muted">${__("Open actions")}: ${p.open_actions.map((a) => esc(a.title)).join("; ")}</span>` : ""}
				</span>
				<span class="pm-actions"></span></div>`).appendTo($c);
			const $a = $r.find(".pm-actions");
			const can_update = this.s.can_run || p.priority_owner === frappe.session.user;
			if (can_update && this.m.status !== "Published") {
				if (p.kind === "Measured") {
					$(`<button class="btn btn-xs ${red ? "btn-default" : "btn-primary"}">${__("On track")}</button>`).appendTo($a)
						.on("click", () => this.call("update_priority", { priority: p.name, status: "On Track" }));
					$(`<button class="btn btn-xs ${red ? "btn-danger" : "btn-default"}">${__("Off track")}</button>`).appendTo($a)
						.on("click", () => this.call("update_priority", { priority: p.name, status: "Off Track" }));
				}
				$(`<button class="btn btn-xs btn-default">${__("Update")}</button>`).appendTo($a).on("click", () => this.priority_dialog(p));
			}
			if (this.s.can_contribute && this.m.status !== "Published") {
				$(`<button class="btn btn-xs btn-default">${__("What's blocking it?")}</button>`).appendTo($a)
					.on("click", () => this.issue_dialog({ title: __("Blocking: {0}", [p.title]).slice(0, 140), priority: p.name }));
				$(`<button class="btn btn-xs btn-default">${__("Add action")}</button>`).appendTo($a)
					.on("click", () => this.action_dialog({ priority: p.name, visibility: p.visibility }));
			}
		});
		$c.append(`<div class="pm-muted" style="margin-top:8px">${__("Leaders create priorities from the Priority list; keep three to seven per space.")}</div>`);
		if (this.s.can_run) {
			$(`<button class="btn btn-default btn-sm" style="margin-top:8px">${__("New priority")}</button>`).appendTo($c)
				.on("click", () => frappe.new_doc("Pulse Priority", { space: this.m.space }));
		}
	}

	priority_dialog(p) {
		const fields = [];
		if (p.kind === "Measured") {
			fields.push({ fieldname: "current_value", fieldtype: "Float", label: __("Current value ({0})", [p.unit || ""]), default: p.current_value });
		} else {
			p.milestones.forEach((m) => fields.push({ fieldname: `ms_${m.idx}`, fieldtype: "Check", label: `${esc(m.milestone)} · ${fmt_date(m.due_date)}`, default: m.done }));
		}
		fields.push({ fieldname: "support_needed", fieldtype: "Small Text", label: __("Support needed from management"), default: p.support_needed || "" });
		const d = new frappe.ui.Dialog({
			title: esc(p.title),
			no_focus: true, // the first field may be a checkbox, which cannot be text-selected
			fields,
			primary_action_label: __("Save"),
			primary_action: async (v) => {
				d.hide();
				for (const m of p.milestones || []) {
					const want = v[`ms_${m.idx}`] ? 1 : 0;
					if (p.kind !== "Measured" && want !== (m.done ? 1 : 0)) {
						await this.call("set_milestone", { priority: p.name, idx: m.idx, done: want }, false);
					}
				}
				await this.call("update_priority", {
					priority: p.name,
					current_value: p.kind === "Measured" ? v.current_value : null,
					support_needed: v.support_needed || "",
				});
			},
		});
		this.current_dialog = d;
		d.show();
	}

	render_headlines() {
		const $c = $(`<div class="pm-card"><h5>${__("Headlines")}</h5></div>`).appendTo(this.$main);
		if (!this.s.headlines.length) $c.append(`<div class="pm-muted">${__("No headlines yet.")}</div>`);
		this.s.headlines.forEach((h) => {
			const $r = $(`<div class="pm-row"><span><span class="pm-muted">${__(h.kind)}</span> · ${esc(h.headline)}
				<span class="pm-muted">· ${user_name(h.author)}</span></span><span class="pm-actions"></span></div>`).appendTo($c);
			if (this.s.can_contribute) {
				$(`<button class="btn btn-xs btn-default">${__("Discuss as issue")}</button>`)
					.appendTo($r.find(".pm-actions"))
					.on("click", () => this.issue_dialog({ title: h.headline.slice(0, 140) }));
			}
		});
		if (this.s.can_contribute && this.m.status !== "Published") {
			$(`<button class="btn btn-default btn-sm" style="margin-top:8px">${__("Add headline")}</button>`)
				.appendTo($c)
				.on("click", () => this.headline_dialog());
		}
		const $in = $(`<div class="pm-card"><h5>${__("Messages from other spaces")}</h5></div>`).appendTo(this.$main);
		if (!this.s.incoming_messages.length) $in.append(`<div class="pm-muted">${__("None.")}</div>`);
		this.s.incoming_messages.forEach((msg) => {
			const $r = $(`<div class="pm-row"><span>${esc(msg.message)} <span class="pm-muted">· ${esc(msg.from_space)}</span></span>
				<span class="pm-actions"></span></div>`).appendTo($in);
			if (msg.acknowledged_in) {
				$r.find(".pm-actions").append(`<span class="pm-muted">${__("Acknowledged")}</span>`);
			} else if (this.running()) {
				$(`<button class="btn btn-xs btn-default">${__("Acknowledge")}</button>`)
					.appendTo($r.find(".pm-actions"))
					.on("click", () => this.call("acknowledge_message", { message: msg.name, meeting: this.name }));
			}
		});
	}

	action_row($parent, a, buttons) {
		const flags = [];
		if (a.visibility === "Restricted") flags.push(__("Restricted"));
		if (a.carried_over) flags.push(__("carried {0}×", [a.carried_over]));
		if (a.verified_by) flags.push(__("verified"));
		const $r = $(`<div class="pm-row">
			<span>${esc(a.title)}<br><span class="pm-muted">${user_name(a.assigned_to)} · ${__("due")} ${fmt_date(a.due_date)} · ${__(a.status)}
			${flags.length ? " · " + flags.map(esc).join(", ") : ""}</span></span>
			<span class="pm-actions"></span></div>`).appendTo($parent);
		(buttons || []).forEach(([label, fn, primary]) => {
			$(`<button class="btn btn-xs ${primary ? "btn-primary" : "btn-default"}">${label}</button>`).appendTo($r.find(".pm-actions")).on("click", fn);
		});
		return $r;
	}

	render_action_review() {
		const $c = $(`<div class="pm-card"><h5>${__("Due for review")}</h5></div>`).appendTo(this.$main);
		if (!this.s.to_review.length) $c.append(`<div class="pm-muted">${__("Nothing due since the last meeting.")}</div>`);
		this.s.to_review.forEach((a) => {
			const reviewed = a.reviewed_in === this.name;
			const buttons =
				this.running() && !reviewed
					? [
							[__("Done"), () => this.call("review_action", { action: a.name, meeting: this.name, result: "Done" }), a.status === "Done"],
							[__("Not done"), () => this.call("review_action", { action: a.name, meeting: this.name, result: "Not Done" })],
							[__("Next week"), () => this.call("review_action", { action: a.name, meeting: this.name, result: "Carry" })],
							[__("To issues"), () => this.call("review_action", { action: a.name, meeting: this.name, result: "Issue" })],
					  ]
					: [];
			this.action_row($c, a, buttons);
		});
		const $e = $(`<div class="pm-card"><h5>${__("Completed since last meeting")}</h5></div>`).appendTo(this.$main);
		if (!this.s.done_early.length) $e.append(`<div class="pm-muted">${__("None.")}</div>`);
		this.s.done_early.forEach((a) => this.action_row($e, a));
	}

	render_issues() {
		const $c = $(`<div class="pm-card"><h5>${__("Open issues, most important first")}</h5></div>`).appendTo(this.$main);
		const issues = this.s.issues;
		if (!issues.length) $c.append(`<div class="pm-muted">${__("No open issues.")}</div>`);
		issues.forEach((iss, i) => {
			const $r = $(`<div class="pm-row"><span><strong>${i + 1}.</strong> ${esc(iss.title)}
				<span class="pm-muted">· ${iss.issue_owner ? user_name(iss.issue_owner) : __("no owner")}${iss.visibility === "Restricted" ? " · " + __("Restricted") : ""}</span></span>
				<span class="pm-actions"></span></div>`).appendTo($c);
			const $a = $r.find(".pm-actions");
			if (this.s.can_run && this.m.status !== "Published") {
				if (i > 0) $(`<button class="btn btn-xs btn-default" title="${__("Move up")}">↑</button>`).appendTo($a).on("click", () => this.move_issue(i, -1));
				if (i < issues.length - 1) $(`<button class="btn btn-xs btn-default" title="${__("Move down")}">↓</button>`).appendTo($a).on("click", () => this.move_issue(i, 1));
			}
			$(`<button class="btn btn-xs btn-primary">${__("Solve")}</button>`).appendTo($a).on("click", () => this.solve_dialog(iss));
		});
		this.render_outcomes(this.$main);
	}

	render_outcomes($parent) {
		const $d = $(`<div class="pm-card"><h5>${__("Decisions in this meeting")}</h5></div>`).appendTo($parent);
		if (!this.s.decisions.length) $d.append(`<div class="pm-muted">${__("None yet.")}</div>`);
		this.s.decisions.forEach((d) => {
			$d.append(`<div class="pm-row"><span>${esc(d.decision)}${d.reason ? ` <span class="pm-muted">· ${esc(d.reason)}</span>` : ""}</span>
				<span class="pm-muted">${d.publish ? "" : __("not published")}</span></div>`);
		});
		const $a = $(`<div class="pm-card"><h5>${__("New actions")}</h5></div>`).appendTo($parent);
		if (!this.s.new_actions.length) $a.append(`<div class="pm-muted">${__("None yet.")}</div>`);
		this.s.new_actions.forEach((a) => this.action_row($a, a));
		if (this.s.can_contribute && this.m.status !== "Published") {
			$(`<button class="btn btn-default btn-sm" style="margin-top:8px">${__("Add action")}</button>`).appendTo($a).on("click", () => this.action_dialog());
		}
		if (this.s.closed_issues.length) {
			const $i = $(`<div class="pm-card"><h5>${__("Issues closed in this meeting")}</h5></div>`).appendTo($parent);
			this.s.closed_issues.forEach((iss) => {
				$i.append(`<div class="pm-row"><span>${esc(iss.title)}</span><span class="pm-muted">${__(iss.status)}${iss.escalated_to ? " → " + esc(iss.escalated_to) : ""}</span></div>`);
			});
		}
	}

	render_conclusion() {
		this.render_outcomes(this.$main);
		const $m = $(`<div class="pm-card"><h5>${__("Messages to other spaces")}</h5></div>`).appendTo(this.$main);
		if (!this.s.outgoing_messages.length) $m.append(`<div class="pm-muted">${__("None.")}</div>`);
		this.s.outgoing_messages.forEach((msg) => {
			$m.append(`<div class="pm-row"><span>${esc(msg.message)}<br><span class="pm-muted">${__("to")} ${msg.targets.map(esc).join(", ")}
				${msg.communicator ? " · " + __("communicated by") + " " + user_name(msg.communicator) : ""}</span></span>
				<span class="pm-muted">${__(msg.status)}</span></div>`);
		});
		if (this.s.can_run && ["In Progress", "Concluded"].includes(this.m.status)) {
			$(`<button class="btn btn-default btn-sm" style="margin-top:8px">${__("Add message")}</button>`).appendTo($m).on("click", () => this.message_dialog());
		}
		if (this.s.is_attendee && ["In Progress", "Concluded"].includes(this.m.status)) {
			const mine = this.m.attendees.find((a) => a.user === frappe.session.user) || {};
			const $r = $(`<div class="pm-card"><h5>${__("Your rating (optional)")}</h5><div class="pm-actions"></div>
				<div class="pm-muted" style="margin-top:8px">${__("Average so far")}: ${this.m.average_rating || "–"}</div></div>`).appendTo(this.$main);
			for (let n = 1; n <= 10; n++) {
				$(`<button class="btn btn-xs ${mine.rating === n ? "btn-primary" : "btn-default"}">${n}</button>`)
					.appendTo($r.find(".pm-actions"))
					.on("click", () => this.call("set_rating", { meeting: this.name, rating: n }));
			}
		}
	}

	// ------------------------------------------------------------- minutes and follow-up

	minute_for(topic) {
		return (this.m.minutes || []).find((r) => r.topic === topic);
	}

	render_minutes_box() {
		const sec = this.m.sections[this.viewing - 1];
		if (!sec) return;
		const topic = sec.title;
		const row = this.minute_for(topic);
		const $c = $(`<div class="pm-card"><h5 style="margin-top:0">${__("Minutes")}: ${esc(topic)}</h5></div>`).appendTo(this.$main);
		if (!this.s.can_run || !["Scheduled", "In Progress", "Concluded"].includes(this.m.status)) {
			$c.append(row && row.minutes ? `<div>${row.minutes}</div>` : `<div class="pm-muted">${__("No minutes for this section yet.")}</div>`);
			return;
		}
		const $bar = $(`<div class="pm-dictate-bar"></div>`).appendTo($c);
		const $status = $(`<div class="pm-muted" style="margin-top:6px"></div>`);
		const control = frappe.ui.form.make_control({
			parent: $c,
			df: { fieldtype: "Text Editor", fieldname: `minutes_${this.viewing}`, label: "" },
			render_input: true,
		});
		control.set_value((row && row.minutes) || "");
		$c.append($status);
		let timer = null;
		let last = (row && row.minutes) || "";
		const save = () => {
			const value = control.get_value() || "";
			if (value === last) return;
			last = value;
			$status.text(__("Saving..."));
			frappe.call({ method: PM_API + "save_minute", args: { meeting: this.name, topic, minutes: value }, quiet: true }).then((r) => {
				this.m.minutes = r.message;
				$status.text(__("Saved {0}", [moment().format("HH:mm:ss")]));
			});
		};
		// Save a couple of seconds after typing stops, and when leaving the section.
		control.$wrapper.on("input keyup", () => {
			clearTimeout(timer);
			timer = setTimeout(save, 2000);
		});
		control.df.change = () => {
			clearTimeout(timer);
			timer = setTimeout(save, 2000);
		};
		this.flush_minutes = save;
		const $interim = $(`<div class="pm-interim"></div>`).insertAfter(control.$wrapper);
		// Where dictated text goes: the minutes box on screen now, whichever section that is.
		this.dictation_target = {
			append: (text) => {
				const q = control.quill;
				if (q) {
					const end = Math.max(q.getLength() - 1, 0);
					const before = end ? q.getText(end - 1, 1) : "";
					q.insertText(end, (end && !/\s/.test(before) ? " " : "") + text, "user");
					q.setSelection(q.getLength(), 0, "silent");
				} else {
					control.set_value(((control.get_value() || "") + " " + text).trim());
				}
				clearTimeout(timer);
				timer = setTimeout(save, 1500);
			},
			interim: (text) => $interim.text(text ? "🎙 " + text : ""),
		};
		this.render_dictate_bar($bar);
	}

	// ------------------------------------------------------------- dictation (browser speech to text)

	speech_api() {
		return window.SpeechRecognition || window.webkitSpeechRecognition;
	}

	dictation_lang() {
		try { return localStorage.getItem("pulse_dictation_lang") || "en-US"; } catch (e) { return "en-US"; }
	}

	render_dictate_bar($bar) {
		if (this.m.status !== "In Progress" && this.m.status !== "Concluded") return;
		const other = this.s.dictation && this.s.dictation.by !== frappe.session.user;
		if (!this.speech_api()) {
			$bar.append(`<span class="pm-muted">🎙 ${__("Dictation needs Chrome or Edge.")}</span>`);
			return;
		}
		if (!window.isSecureContext) {
			$bar.append(`<span class="pm-muted">🎙 ${__("Dictation needs the site to be opened over https.")}</span>`);
			return;
		}
		if (this.dictating) {
			$(`<button class="btn btn-sm btn-danger">■ ${__("Stop dictating")}</button>`).appendTo($bar).on("click", () => this.stop_dictation());
			$bar.append(`<span class="pm-muted">${__("Speak clearly; the text appears in this section's minutes. You can correct it as you go.")}</span>`);
			return;
		}
		const $btn = $(`<button class="btn btn-sm btn-default">🎙 ${__("Dictate")}</button>`).appendTo($bar);
		if (other) {
			$btn.prop("disabled", true).attr("title", __("{0} is dictating", [this.s.dictation.by_name]));
		} else {
			$btn.on("click", () => this.start_dictation());
		}
		const $lang = $(`<select class="form-control input-xs" style="width:auto; display:inline-block" title="${__("Accent")}">
			<option value="en-US">English (US)</option><option value="en-GB">English (UK)</option><option value="en-CA">English (Canada)</option>
			</select>`).appendTo($bar);
		$lang.val(this.dictation_lang()).on("change", () => { try { localStorage.setItem("pulse_dictation_lang", $lang.val()); } catch (e) { /* private window */ } });
	}

	async start_dictation() {
		let agreed = false;
		try { agreed = localStorage.getItem("pulse_dictation_ok") === "1"; } catch (e) { /* private window */ }
		if (!agreed) {
			const ok = await new Promise((resolve) => frappe.confirm(
				__("Dictation uses your browser's speech service: Chrome and Edge send the audio to Google or Microsoft to turn it into text. Do not dictate anything that must stay inside the company. Everyone in the meeting will see that dictation is on. Continue?"),
				() => resolve(true), () => resolve(false)));
			if (!ok) return;
			try { localStorage.setItem("pulse_dictation_ok", "1"); } catch (e) { /* private window */ }
		}
		const state = await frappe.call({ method: PM_API + "set_dictation", args: { meeting: this.name, on: 1 } });
		const Rec = this.speech_api();
		const rec = new Rec();
		rec.lang = this.dictation_lang();
		rec.continuous = true;
		rec.interimResults = true;
		rec.onresult = (e) => {
			let interim = "";
			for (let i = e.resultIndex; i < e.results.length; i++) {
				const text = e.results[i][0].transcript.trim();
				if (!text) continue;
				if (e.results[i].isFinal) {
					const sentence = text.charAt(0).toUpperCase() + text.slice(1) + (/[.?!]$/.test(text) ? "" : ".");
					this.dictation_target && this.dictation_target.append(sentence);
				} else {
					interim += text + " ";
				}
			}
			this.dictation_target && this.dictation_target.interim(interim.trim());
		};
		rec.onerror = (e) => {
			if (e.error === "no-speech" || e.error === "aborted") return; // silence: keep listening
			const why = {
				"not-allowed": __("The browser blocked the microphone. Allow it in the address bar, then press Dictate again."),
				"service-not-allowed": __("The browser blocked the microphone. Allow it in the address bar, then press Dictate again."),
				"audio-capture": __("No microphone was found on this computer."),
				network: __("The speech service could not be reached. Check the internet connection."),
			}[e.error] || __("Dictation stopped: {0}", [e.error]);
			this.stop_dictation();
			frappe.msgprint(why);
		};
		// The browser ends recognition after a pause; keep going until Stop is pressed.
		rec.onend = () => {
			if (this.dictation === rec) {
				try { rec.start(); } catch (err) { setTimeout(() => this.dictation === rec && rec.start(), 300); }
			}
		};
		this.dictation = rec;
		this.dictating = this.name;
		this.s.dictation = state && state.message;
		rec.start();
		this.dictation_beat = setInterval(() => frappe.call({ method: PM_API + "set_dictation", args: { meeting: this.dictating, on: 1 }, quiet: true }), 60000);
		this.render();
	}

	stop_dictation(leaving = false) {
		const rec = this.dictation;
		const meeting = this.dictating;
		this.dictation = null;
		this.dictating = null;
		clearInterval(this.dictation_beat);
		if (rec) { try { rec.stop(); } catch (e) { /* already stopped */ } }
		if (this.dictation_target) this.dictation_target.interim("");
		if (!meeting) return;
		if (leaving && navigator.sendBeacon) {
			const body = new FormData();
			body.append("meeting", meeting); body.append("on", "0"); body.append("csrf_token", frappe.csrf_token);
			navigator.sendBeacon("/api/method/" + PM_API + "set_dictation", body);
			return;
		}
		frappe.call({ method: PM_API + "set_dictation", args: { meeting, on: 0 }, quiet: true });
		if (this.s && this.name === meeting) {
			this.s.dictation = null;
			this.render();
		}
	}

	show_dictation_banner() {
		$(this.page.main).find(".pm-dictation").remove();
		const d = this.s && this.s.dictation;
		if (!d) return;
		const mine = d.by === frappe.session.user;
		const $b = $(`<div class="pm-dictation" role="status">
			<div><span class="pm-dot"></span><b>${__("Dictation on")}</b> · ${mine ? __("You are") : esc(d.by_name) + " " + __("is")}
			${__("turning speech into minutes. The audio is processed by the browser's speech service.")}</div></div>`);
		if (mine) $(`<button class="btn btn-sm" style="background:#fff;color:#b42318">■ ${__("Stop")}</button>`).appendTo($b).on("click", () => this.stop_dictation());
		$b.prependTo(this.page.main);
	}

	minutes_dialog() {
		const topics = (this.m.minutes || []).map((r) => r.topic);
		const d = new frappe.ui.Dialog({
			title: __("Minutes for a topic"),
			size: "large",
			fields: [
				{ fieldname: "existing", fieldtype: "Select", label: __("Topic"), options: [""].concat(topics).join("\n"),
					description: __("Pick a topic to edit, or type a new one below.") },
				{ fieldname: "topic", fieldtype: "Data", label: __("New topic"), description: __("For example: Inventory, Fleet tracking") },
				{ fieldname: "minutes", fieldtype: "Text Editor", label: __("Minutes") },
			],
			primary_action_label: __("Save"),
			primary_action: (v) => {
				const topic = (v.topic || v.existing || "").trim();
				if (!topic) frappe.throw(__("Choose or name a topic."));
				d.hide();
				this.call("save_minute", { meeting: this.name, topic, minutes: v.minutes || "" });
			},
		});
		d.fields_dict.existing.df.onchange = () => {
			const row = this.minute_for(d.get_value("existing"));
			d.set_value("minutes", (row && row.minutes) || "");
		};
		this.current_dialog = d;
		d.show();
	}

	followup_dialog() {
		const d = new frappe.ui.Dialog({ title: __("Follow-up"), size: "large", fields: [{ fieldtype: "HTML", fieldname: "f" }] });
		d.show();
		if (window.pulse_followup) window.pulse_followup(d.fields_dict.f.$wrapper, this.name);
	}

	// ------------------------------------------------------------- dialogs

	move_issue(i, step) {
		const order = this.s.issues.map((x) => x.name);
		const [item] = order.splice(i, 1);
		order.splice(i + step, 0, item);
		this.call("rank_issues", { space: this.m.space, order: JSON.stringify(order) });
	}

	member_options() {
		return this.s.members.map((u) => ({ value: u, label: frappe.user.full_name(u) || u }));
	}

	issue_dialog(defaults = {}) {
		const d = new frappe.ui.Dialog({
			title: __("Add issue"),
			fields: [
				{ fieldname: "title", fieldtype: "Data", label: __("Issue"), reqd: 1, default: defaults.title || "" },
				{ fieldname: "details", fieldtype: "Small Text", label: __("Details") },
				{ fieldname: "issue_owner", fieldtype: "Link", options: "User", label: __("Owner"), default: frappe.session.user },
				{ fieldname: "visibility", fieldtype: "Select", options: "Team\nRestricted", default: "Team", label: __("Visibility") },
			],
			primary_action_label: __("Add"),
			primary_action: (v) => {
				d.hide();
				this.call("add_issue", { space: this.m.space, meeting: this.name, title: v.title, details: frappe.utils.escape_html(v.details || ""), issue_owner: v.issue_owner, visibility: v.visibility, priority: defaults.priority });
			},
		});
		d.show();
	}

	headline_dialog() {
		const d = new frappe.ui.Dialog({
			title: __("Add headline"),
			fields: [
				{ fieldname: "headline", fieldtype: "Small Text", label: __("Headline"), reqd: 1 },
				{ fieldname: "kind", fieldtype: "Select", options: "Customer\nStaff\nGeneral", default: "General", label: __("Kind") },
			],
			primary_action_label: __("Add"),
			primary_action: (v) => {
				d.hide();
				this.call("add_headline", { space: this.m.space, meeting: this.name, headline: v.headline, kind: v.kind });
			},
		});
		d.show();
	}

	action_dialog(defaults = {}) {
		const d = new frappe.ui.Dialog({
			title: __("Add action"),
			fields: [
				{ fieldname: "title", fieldtype: "Data", label: __("Action"), reqd: 1, default: defaults.title || "" },
				{ fieldname: "assigned_to", fieldtype: "Link", options: "User", label: __("Owner"), reqd: 1 },
				{ fieldname: "due_date", fieldtype: "Date", label: __("Due"), reqd: 1, default: this.s.default_due },
				{ fieldname: "visibility", fieldtype: "Select", options: "Team\nRestricted", default: defaults.visibility || "Team", label: __("Visibility") },
				{ fieldname: "evidence_required", fieldtype: "Check", label: __("Needs evidence to complete") },
				{ fieldname: "details", fieldtype: "Small Text", label: __("Details") },
			],
			primary_action_label: __("Add"),
			primary_action: (v) => {
				d.hide();
				this.call("add_action", { space: this.m.space, meeting: this.name, issue: defaults.issue, decision: defaults.decision, priority: defaults.priority, ...v });
			},
		});
		d.show();
	}

	solve_dialog(iss) {
		const d = new frappe.ui.Dialog({
			title: esc(iss.title),
			size: "large",
			fields: [
				{ fieldtype: "HTML", fieldname: "info", options: `<div class="pm-muted">${iss.details || ""}</div>` },
				{ fieldname: "discussion", fieldtype: "Text Editor", label: __("Discussion notes"), default: iss.discussion || "" },
				{ fieldname: "decision", fieldtype: "Small Text", label: __("Decision (optional)") },
				{ fieldname: "reason", fieldtype: "Small Text", label: __("Why (for the decision)") },
				{ fieldname: "review_date", fieldtype: "Date", label: __("Review the decision on") },
				{ fieldtype: "Section Break", label: __("Action (optional)") },
				{ fieldname: "action_title", fieldtype: "Data", label: __("Action") },
				{ fieldname: "action_owner", fieldtype: "Link", options: "User", label: __("Owner"), mandatory_depends_on: "action_title" },
				{ fieldtype: "Column Break" },
				{ fieldname: "action_due", fieldtype: "Date", label: __("Due"), default: this.s.default_due },
				{ fieldname: "action_visibility", fieldtype: "Select", options: "Team\nRestricted", default: iss.visibility || "Team", label: __("Visibility") },
				{ fieldtype: "Section Break", label: __("Outcome") },
				{ fieldname: "outcome", fieldtype: "Select", label: __("Outcome"), options: "Solved\nKeep open\nDropped\nEscalate", default: "Solved" },
				{ fieldname: "target_space", fieldtype: "Link", options: "Pulse Space", label: __("Escalate to"), depends_on: "eval:doc.outcome=='Escalate'" },
				{ fieldname: "resolution", fieldtype: "Small Text", label: __("Resolution"), depends_on: "eval:['Solved','Dropped'].includes(doc.outcome)" },
			],
			primary_action_label: __("Save"),
			primary_action: async (v) => {
				d.hide();
				await this.call("update_issue_notes", { issue: iss.name, discussion: v.discussion || "" }, false);
				let decision = null;
				if (v.decision) {
					decision = await this.call("add_decision", { space: this.m.space, meeting: this.name, issue: iss.name, decision: v.decision, reason: v.reason, review_date: v.review_date }, false);
				}
				if (v.action_title) {
					await this.call("add_action", {
						space: this.m.space, meeting: this.name, issue: iss.name, decision: decision && decision.name,
						title: v.action_title, assigned_to: v.action_owner, due_date: v.action_due, visibility: v.action_visibility,
					}, false);
				}
				if (v.outcome === "Escalate") {
					if (!v.target_space) frappe.throw(__("Choose the space to escalate to."));
					await this.call("escalate_issue", { issue: iss.name, target_space: v.target_space, meeting: this.name }, false);
				} else if (v.outcome !== "Keep open") {
					await this.call("close_issue", { issue: iss.name, outcome: v.outcome, resolution: v.resolution, meeting: this.name }, false);
				}
				await this.load(this.name);
			},
		});
		this.current_dialog = d;
		d.show();
	}

	message_dialog() {
		const d = new frappe.ui.Dialog({
			title: __("Message to other spaces"),
			fields: [
				{ fieldname: "message", fieldtype: "Small Text", label: __("Message"), reqd: 1 },
				{ fieldname: "targets", fieldtype: "Table MultiSelect", options: "Pulse Message Target", label: __("Send to"), reqd: 1 },
				{ fieldname: "communicator", fieldtype: "Link", options: "User", label: __("Person to communicate it (optional)") },
			],
			primary_action_label: __("Add"),
			primary_action: (v) => {
				d.hide();
				const targets = (v.targets || []).map((t) => t.space);
				this.call("add_message", { from_space: this.m.space, meeting: this.name, message: v.message, targets: JSON.stringify(targets), communicator: v.communicator });
			},
		});
		d.show();
	}

	conclude() {
		if (this.flush_minutes) this.flush_minutes();
		frappe.confirm(__("Conclude the meeting? Timers stop and the secretary can review and publish the summary."), () => {
			// Straight on to the review: the summary is only emailed once it is published.
			this.call("conclude_meeting", { meeting: this.name }).then(() => this.publish_dialog());
		});
	}

	async publish_dialog() {
		const p = await this.call("publish_preview", { meeting: this.name }, false);
		const fields = [{ fieldtype: "HTML", fieldname: "intro", options: `<p>${__("Untick anyone who should not receive this. Nothing is sent until you publish.")}</p>` }];
		fields.push({ fieldtype: "Section Break", label: __("Full summary ({0})", [p.full.length]) });
		p.full.forEach((r, i) => fields.push({ fieldtype: "Check", fieldname: `full_${i}`, label: esc(r.full_name), default: 1 }));
		if (p.action_only.length) {
			fields.push({ fieldtype: "Section Break", label: __("Their action only") });
			p.action_only.forEach((r, i) =>
				fields.push({ fieldtype: "Check", fieldname: `act_${i}`, label: `${esc(r.full_name)}: ${r.actions.map(esc).join("; ")}`, default: 1 })
			);
		}
		if (p.messages.length) {
			fields.push({ fieldtype: "Section Break", label: __("Messages to other spaces") });
			p.messages.forEach((m, i) =>
				fields.push({ fieldtype: "Check", fieldname: `msg_${i}`, label: `${esc(m.message)} → ${m.targets.map(esc).join(", ")} (${m.recipient_count})`, default: 1 })
			);
		}
		fields.push({ fieldtype: "Section Break", label: __("Personal email") });
		fields.push({ fieldtype: "Check", fieldname: "personal", default: 1,
			label: __("Also send each person their own Pulse list: their open and overdue actions, issues, priorities and next meetings across all teams") });
		fields.push({ fieldtype: "Section Break", label: __("Summary") });
		fields.push({ fieldtype: "HTML", fieldname: "summary", options: `<div class="pm-card">${p.summary_html}</div>` });
		const d = new frappe.ui.Dialog({
			title: __("Review and publish"),
			size: "large",
			fields,
			primary_action_label: __("Publish"),
			primary_action: (v) => {
				const exclude_users = [];
				p.full.forEach((r, i) => !v[`full_${i}`] && exclude_users.push(r.user));
				p.action_only.forEach((r, i) => !v[`act_${i}`] && exclude_users.push(r.user));
				const exclude_messages = p.messages.filter((m, i) => !v[`msg_${i}`]).map((m) => m.name);
				d.hide();
				this.call("publish", { meeting: this.name, exclude_users: JSON.stringify(exclude_users), exclude_messages: JSON.stringify(exclude_messages), personal: v.personal ? 1 : 0 }).then(() =>
					frappe.show_alert({ message: __("Published"), indicator: "green" })
				);
			},
		});
		d.show();
	}
}
