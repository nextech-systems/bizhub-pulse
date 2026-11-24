/* Host permission is checked by the server for every launch. */
window.bizpulse_video = (() => {
  const method = "bizhub_pulse.jitsi.";
  async function request(action, meeting) {
    const r = await frappe.call({method: method + action, args: {meeting}, type: "POST"});
    return r.message;
  }
  function guest(link) {
    const dialog = new frappe.ui.Dialog({title: __("Guest invitation"), fields: [
      {fieldname: "link", fieldtype: "Data", label: __("Guest link"), read_only: 1, default: link},
      {fieldtype: "HTML", options: "<p>Guests use this link without an ERPNext account and wait for a host.</p>"}
    ]});
    dialog.show();
  }
  function getHttpsUrl(rawUrl) {
    const url = new URL(rawUrl);
    if (url.protocol !== "https:" || url.username || url.password) {
      throw new Error("Unexpected meeting URL");
    }
    return url;
  }
  async function launch(meeting, expectedOrigin) {
    // Open immediately after the click so browser popup protection does not block it.
    const tab = window.open("about:blank", "_blank");
    if (!tab) { frappe.msgprint(__("Allow popups for ERPNext, then try again.")); return; }
    tab.document.title = "Opening BizPulse";
    tab.document.body.textContent = "Opening your meeting…";
    tab.opener = null;
    try {
      const data = await request("launch_video", meeting);
      const endpoint = getHttpsUrl(data.endpoint);
      if (endpoint.origin !== expectedOrigin || endpoint.pathname !== "/host/erp-join"
          || endpoint.search || endpoint.hash) {
        throw new Error("Unexpected meeting endpoint");
      }
      const form = tab.document.createElement("form");
      form.method = "POST"; form.action = endpoint.href;
      const input = tab.document.createElement("input");
      input.type = "hidden"; input.name = "ticket"; input.value = data.ticket;
      form.appendChild(input); tab.document.body.replaceChildren(form); form.submit();
    } catch (error) { tab.close(); }
  }
  async function controls(meeting, add, current) {
    try {
      const data = await request("get_video_access", meeting);
      if (!current() || !data || !data.guest_url) return;
      const guestUrl = getHttpsUrl(data.guest_url);
      if (data.can_host) add(__("Host video meeting"), () => launch(meeting, guestUrl.origin));
      add(__("Guest invitation"), () => guest(guestUrl.href));
      add(__("Join video as guest"), () => window.open(guestUrl.href, "_blank", "noopener,noreferrer"));
    } catch (error) { /* Frappe displays the server's permission/configuration error. */ }
  }
  return {controls};
})();
frappe.ui.form.on("Pulse Meeting", {
  refresh(frm) {
    if (frm.is_new()) return;
    const name = frm.doc.name;
    window.bizpulse_video.controls(name,
      (label, action) => frm.add_custom_button(label, action, __("Video")),
      () => frm.doc.name === name);
  }
});
