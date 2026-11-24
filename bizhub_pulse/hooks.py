app_name = "bizhub_pulse"
app_title = "BizHub Pulse"
app_publisher = "NextTech BizHub"
app_description = "Meetings, decisions and follow-through inside ERPNext"
app_email = "info@nextechbizhub.com"
app_license = "MIT"
required_apps = ["erpnext"]

app_include_js = ["/assets/bizhub_pulse/js/pulse_links.js", "/assets/bizhub_pulse/js/pulse_followup.js"]
doctype_js = {"Pulse Meeting": "public/js/pulse_meeting_form.js", "Pulse Settings": "public/js/pulse_settings.js"}

after_install = "bizhub_pulse.install.after_install"
after_migrate = "bizhub_pulse.install.after_migrate"
boot_session = "bizhub_pulse.install.boot_session"

_P = "bizhub_pulse.visibility."
has_permission = {
	"Pulse Space": _P + "has_permission",
	"Pulse Meeting": _P + "has_permission",
	"Pulse Meeting Notes": _P + "has_permission",
	"Pulse Issue": _P + "has_permission",
	"Pulse Decision": _P + "has_permission",
	"Pulse Action": _P + "has_permission",
	"Pulse Headline": _P + "has_permission",
	"Pulse Message": _P + "has_permission",
	"Pulse Priority": _P + "has_permission",
	"Version": _P + "version_has_permission",
	"Comment": _P + "comment_has_permission",
}
permission_query_conditions = {
	"Pulse Space": _P + "space_conditions",
	"Pulse Meeting": _P + "meeting_conditions",
	"Pulse Meeting Notes": _P + "notes_conditions",
	"Pulse Issue": _P + "issue_conditions",
	"Pulse Decision": _P + "decision_conditions",
	"Pulse Action": _P + "action_conditions",
	"Pulse Headline": _P + "headline_conditions",
	"Pulse Message": _P + "message_conditions",
	"Pulse Priority": _P + "priority_conditions",
	"Version": _P + "version_conditions",
	"Comment": _P + "comment_conditions",
}

doc_events = {
	"DocShare": {"before_insert": _P + "block_share", "validate": _P + "block_share"},
	"Has Role": {"on_update": _P + "clear_cache", "on_trash": _P + "clear_cache"},
	"Employee": {"on_update": _P + "clear_cache"},
}

scheduler_events = {
	"daily": ["bizhub_pulse.scheduler.generate_meetings"],
	"cron": {"0 7 * * *": ["bizhub_pulse.scheduler.daily_digest", "bizhub_pulse.scheduler.meeting_reminders", "bizhub_pulse.scheduler.unpublished_reminders"]},
}

# BizPulse video controls; server checks role and meeting access.
app_include_js.append("/assets/bizhub_pulse/js/pulse_jitsi.js")
