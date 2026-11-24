# BizHub Pulse

Meetings, decisions and follow-through inside ERPNext. A team meets on a fixed
rhythm, checks last week's commitments, solves its most important issues,
records decisions and leaves with owned actions. The next meeting shows whether
they were done.

Version 0.3.2 (Stage 1 plus quarterly priorities, minutes, follow-up, dictation, the Tangent button and Jitsi video). Designed for Frappe and ERPNext v14 and v15. See the [MIT license](LICENSE).

## What's in Stage 1

| Part | Where |
| --- | --- |
| Spaces: Company, Team, Person and Project; Private or Secret; members with roles (Leader, Facilitator, Secretary, Member, Observer); meeting rhythm | Pulse Space |
| Meeting templates with timed sections (three starter templates) | Pulse Meeting Template |
| Meetings: agenda copied from the template, attendance, section timers, optional 1-10 ratings, published summary | Pulse Meeting, `/app/pulse-room/<name>` |
| Minutes by topic inside each meeting: a box under every agenda section that saves as the secretary types, plus extra topics; included in the published summary | Pulse Meeting (Minutes) |
| Dictation into the minutes (Chrome or Edge, https): the facilitator or secretary presses Dictate and speech is typed into the minutes of the section on screen, editable as it arrives; everyone on the meeting screen sees a red "Dictation on" banner. The browser's speech service (Google or Microsoft) processes the audio, which the user is told before the first use | Meeting screen |
| Live Follow-up on every meeting: its actions with owner, due date and status (open, done, verified, overdue), issues raised or settled there, and its decisions | Pulse Meeting form and meeting screen |
| Tangent button: anyone in a running meeting flags that the talk has drifted; everyone on the meeting screen sees it at once, the facilitator can park the topic as an issue, and the count goes in the summary | Meeting screen |
| Jitsi video (optional): a Video menu on each meeting; hosting needs the BizPulse Meeting Host role and access to that meeting; guest links carry no moderator rights. Shown only on sites configured with the Jitsi bridge | `jitsi.py` |
| Draft notes visible only to the people running the meeting | Pulse Meeting Notes |
| Issues that persist across meetings, ranked, with escalation to another space | Pulse Issue |
| Decision register: reason, approver, review date; published decisions are superseded, never edited | Pulse Decision |
| Actions: one owner, due in 7 days by default, Done or Not Done, carry-over count, evidence and verification | Pulse Action |
| Quarterly priorities: one owner, a due date and "done looks like"; either Milestones (off track automatically when a step is overdue) or Measured (start, target, current value); contributors; support needed; actions, issues and decisions link to them | Pulse Priority |
| Headlines and cascading messages to other spaces | Pulse Headline, Pulse Message |
| My Pulse: my actions, my issues, my meetings | `/app/my-pulse` |
| "Pulse" buttons and an "Open in Pulse" sidebar on chosen ERPNext forms | Pulse Settings |
| Emails at publishing: the summary and minutes to the team, and each person their own Pulse list (new, overdue and upcoming actions, issues, priorities, what they wait on from others, next meetings) | Review and publish |
| Recurring meetings, a daily digest, meeting-eve reminders, and a morning reminder to the facilitator, secretary and leaders while a concluded meeting is still unpublished | `scheduler.py` |

## Who sees what

The visibility hooks in `visibility.py` evaluate stored records and define the expected access rules below. Verify form, list, search, API, and linked-record behavior on your staging site.

| Content | Who can read |
| --- | --- |
| Company space | Every Pulse User |
| Private team or project space | Members and Pulse Admins (others see only that it exists) |
| Secret space | Members and Pulse Admins |
| Person space | The person and their managers (Employee "Reports To" chain) |
| Issue or action, Team visibility | Space members, its owner and its assigner |
| Issue or action, Restricted | Owner, assigner, the owner's managers, space Leaders |
| Priority | As an issue (Team or Restricted), plus its listed contributors. Leaders create and change the commitment; the owner reports progress |
| Draft notes | Facilitator, secretary, Leaders |
| Published summary | The recipients chosen at publishing, plus space members |
| Cascading message | Members of the sending and receiving spaces |

Pulse records cannot be shared with Frappe's Share button: access comes from
space membership only. Pulse Admin sees everything. Change history (Version)
and comments on a Pulse record follow that record's rule too, so a System
Manager cannot read a Secret space's history from the Version or Comment lists.

Pulse adds no Custom Fields, Property Setters or method overrides to Frappe or
ERPNext. It works alongside `todo_privacy` (recommended, not required).
Its Version and Comment hooks decide only for Pulse records; on install and
migrate Pulse places itself just before any other app that guards Version or
Comment (never before ERPNext), so that app's hook is still asked first.

## Roles

- **Pulse User**: give it to everyone who takes part in meetings.
- **Pulse Admin**: creates spaces, manages membership, reads everything.
- **BizPulse Meeting Host** (optional): may start the Jitsi video call as moderator for meetings they can open.

If users have a Role Profile, add Pulse User to the profile: ERPNext rebuilds a
user's roles from their profile on every save.

## Install

```bash
bench get-app https://github.com/nextech-systems/bizhub-pulse.git
bench --site SITE install-app bizhub_pulse
bench build --app bizhub_pulse        # install-app does not build the app's JS
bench restart
```

Installing from an archive instead: copy the folder to `apps/`, run
`./env/bin/pip install -e apps/bizhub_pulse`, and add `bizhub_pulse` on its own
line in `sites/apps.txt` (check the file ends with a newline first).

Then: Pulse Settings (check reporting lines; choose which forms get Pulse
buttons), create spaces, add members, set each space's rhythm and template.

## Optional integrations

**ToDo Privacy** can be installed alongside BizHub Pulse. Verify that creating and opening linked tasks behaves as expected for each Pulse role.

**Jitsi** requires a compatible meeting bridge, a private `bizpulse_jitsi` site configuration, and authorization for hosting. Set the bridge's HTTPS origin in the administrator-owned bridge export and import it with `bizhub_pulse.jitsi.configure`. The browser checks the host ticket's destination against the meeting origin before submitting it. Test host and guest access on a staging site before enabling video.

**Dictation** depends on the browser's speech service. Review the browser and organization settings before enabling it for sensitive meetings.

## Tests

```bash
bench --site staging.example.com run-tests --app bizhub_pulse
```

Use a disposable site with tests enabled and outbound email muted. Start with a private test space and two user accounts. Verify membership, draft notes, publishing, actions and reminders, and optional integrations. The original release includes a site test suite; this repository snapshot passed syntax and secret checks without a site-level run.

## Upgrading to 0.3.2

Replace the app folder, `bench build --app bizhub_pulse`, clear the cache and
restart. No migrate is needed (no database change), but running it does no harm.

## Upgrading to 0.3.1

Replace the app folder, run `bench --site SITE migrate` (adds the tangent
count), `bench build --app bizhub_pulse`, then restart. The Tangent button needs
Frappe's live updates (node socketio), which a standard production bench runs.
0.3.1 already contains the Jitsi integration, so replacing a 0.3.0 folder that
had it installed by its own installer loses nothing; its settings stay in
site_config.json.

## Upgrading to 0.3.0

Replace the app folder, run `bench --site SITE migrate`, `bench build --app
bizhub_pulse`, then restart. Minutes and Follow-up need no setup.

## Upgrading from 0.1.0

Replace the app folder, then `bench --site SITE migrate`. A patch adds a
Priorities section to the two weekly starter templates (Issue solving gives up
5 minutes); templates that already have one are left alone.

## Later stages

2. Scorecards calculated from ERPNext, quarterly priorities, outcome review.
3. Recording and transcription with reviewed AI drafts.
4. Internal PBX conference rooms.
5. Creating Teams and Zoom meetings and retrieving their recordings.
